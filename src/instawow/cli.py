from __future__ import annotations

import asyncio
import enum
import textwrap
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence, Set
from datetime import datetime, timezone
from functools import cached_property, partial
from itertools import chain, repeat
from pathlib import Path
from typing import Any, Literal, NoReturn, TypeVar, overload

import click
import click.types
from attrs import asdict, evolve, fields, resolve_types
from loguru import logger
from typing_extensions import Self

from . import __version__, db, models
from . import manager as _manager
from . import results as R
from .common import ChangelogFormat, Defn, Flavour, Strategy
from .config import Config, GlobalConfig, config_converter, setup_logging
from .http import TraceRequestCtx, init_web_client
from .plugins import load_plugins
from .utils import StrEnum, all_eq, gather, reveal_folder, tabulate, uniq

_T = TypeVar('_T')
_TStrEnum = TypeVar('_TStrEnum', bound=StrEnum)


class Report:
    SUCCESS_SYMBOL = click.style('✓', fg='green')
    FAILURE_SYMBOL = click.style('✗', fg='red')
    WARNING_SYMBOL = click.style('!', fg='blue')

    def __init__(
        self,
        results: Iterable[tuple[Defn, R.ManagerResult]],
        filter_fn: Callable[[R.ManagerResult], bool] = lambda _: True,
    ) -> None:
        self.results = list(results)
        self.filter_fn = filter_fn

    @property
    def exit_code(self) -> int:
        return any(
            isinstance(r, (R.ManagerError, R.InternalError)) and self.filter_fn(r)
            for _, r in self.results
        )

    @classmethod
    def _result_type_to_symbol(cls, result: R.ManagerResult) -> str:
        if isinstance(result, R.InternalError):
            return cls.WARNING_SYMBOL
        elif isinstance(result, R.ManagerError):
            return cls.FAILURE_SYMBOL
        else:
            return cls.SUCCESS_SYMBOL

    def __str__(self) -> str:
        return '\n'.join(
            f'{self._result_type_to_symbol(r)} {click.style(defn_to_urn(a), bold=True)}\n'
            f'{textwrap.fill(r.message, initial_indent=" " * 2, subsequent_indent=" " * 4)}'
            for a, r in self.results
            if self.filter_fn(r)
        )

    def generate(self) -> None:
        mw: _CtxObjWrapper | None = click.get_current_context().obj

        if mw and mw.manager.config.global_config.auto_update_check:
            from ._version import is_outdated

            outdated, new_version = mw.run_with_progress(
                is_outdated(mw.manager.config.global_config)
            )
            if outdated:
                click.echo(f'{self.WARNING_SYMBOL} instawow v{new_version} is available')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self) -> NoReturn:
        self.generate()
        ctx = click.get_current_context()
        ctx.exit(self.exit_code)


class _CtxObjWrapper:
    def __init__(self, ctx: click.Context) -> None:
        self._ctx = ctx

    @cached_property
    def manager(self) -> _manager.Manager:
        global_config = GlobalConfig.read().ensure_dirs()
        try:
            config = Config.read(global_config, self._ctx.params['profile']).ensure_dirs()
        except FileNotFoundError:
            config = self._ctx.invoke(configure)

        setup_logging(config.logging_dir, *self._ctx.params['debug'])

        return _manager.Manager.from_config(config)

    def run_with_progress(self, awaitable: Awaitable[_T]) -> _T:
        cache_dir = self.manager.config.global_config.cache_dir
        params = self._ctx.params

        if any(params['debug']):

            async def run():
                async with init_web_client(cache_dir, no_cache=params['no_cache']) as web_client:
                    _manager.contextualise(web_client=web_client)
                    return await awaitable

        else:
            from contextlib import contextmanager

            import aiohttp
            from prompt_toolkit.shortcuts import ProgressBar, ProgressBarCounter

            from ._cli_prompts import make_progress_bar

            def init_cli_web_client(progress_bar: ProgressBar, tickers: set[asyncio.Task[None]]):
                TICK_INTERVAL = 0.1

                async def do_on_request_end(
                    client_session: aiohttp.ClientSession,
                    trace_config_ctx: Any,
                    params: aiohttp.TraceRequestEndParams,
                ):
                    trace_request_ctx: TraceRequestCtx = trace_config_ctx.trace_request_ctx
                    if trace_request_ctx:
                        response = params.response
                        label = (
                            'Downloading '
                            + defn_to_urn(
                                Defn(
                                    trace_request_ctx['pkg'].source, trace_request_ctx['pkg'].slug
                                )
                            )
                            if trace_request_ctx['report_progress'] == 'pkg_download'
                            else trace_request_ctx['label']
                        )
                        # When the total is ``None`` the progress bar is
                        # in an "indeterminate" state.
                        # We cannot display progress for encoded responses because
                        # the size before decoding is not exposed by the
                        # aiohttp streaming API
                        total = (
                            None
                            if aiohttp.hdrs.CONTENT_ENCODING in response.headers
                            else response.content_length
                        )

                        counters = progress_bar.counters

                        async def ticker():
                            counter = ProgressBarCounter[object](
                                progress_bar=progress_bar, label=label, total=total
                            )
                            counters.append(counter)
                            try:
                                while not response.content.is_eof():
                                    counter.items_completed = response.content.total_bytes
                                    progress_bar.invalidate()
                                    await asyncio.sleep(TICK_INTERVAL)
                            finally:
                                counters.remove(counter)

                        tickers.add(asyncio.create_task(ticker()))

                trace_config = aiohttp.TraceConfig()
                trace_config.on_request_end.append(do_on_request_end)
                trace_config.freeze()
                return init_web_client(
                    cache_dir, no_cache=params['no_cache'], trace_configs=[trace_config]
                )

            @contextmanager
            def cancel_tickers(progress_bar: ProgressBar):
                tickers: set[asyncio.Task[None]] = set()
                try:
                    yield tickers
                finally:
                    for ticker in tickers:
                        ticker.cancel()
                    progress_bar.invalidate()

            async def run():
                with make_progress_bar() as progress_bar, cancel_tickers(progress_bar) as tickers:
                    async with init_cli_web_client(progress_bar, tickers) as web_client:
                        _manager.contextualise(web_client=web_client)
                        return await awaitable

        return asyncio.run(run())


def _with_manager(fn: Callable[..., object]):
    def wrapper(ctx: click.Context, __: click.Parameter, value: object):
        return fn(ctx.obj.manager, value)

    return wrapper


class _StrEnumChoiceParam(click.Choice):
    def __init__(
        self,
        choice_enum: type[_TStrEnum],
        case_sensitive: bool = True,
    ) -> None:
        super().__init__(
            choices=list(choice_enum),
            case_sensitive=case_sensitive,
        )
        self.__choice_enum = choice_enum

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        converted_value = super().convert(value, param, ctx)
        return self.__choice_enum(converted_value)


class _ManyOptionalChoiceValueParam(click.types.CompositeParamType):
    def __init__(
        self,
        choice_param: click.Choice,
        *,
        value_types: Mapping[str, click.types.ParamType] = {},
    ) -> None:
        super().__init__()
        self.__choice_param = choice_param
        self.__value_types = value_types

    def __parse_value(self, value: tuple[str, ...]):
        return (
            (k, v, self.__choice_param, vc)
            for r in value
            for k, _, v in (r.partition('='),)
            for vc in (self.__value_types.get(k),)
        )

    @property
    def arity(self) -> int:
        return -1

    def convert(
        self, value: tuple[str, ...], param: click.Parameter | None, ctx: click.Context | None
    ) -> Any:
        return {
            kc.convert(k, param, ctx): vc.convert(v, param, ctx) if vc and v else (v or None)
            for k, v, kc, vc in self.__parse_value(value)
        }

    def get_metavar(self, param: click.Parameter) -> str:
        return f'{{{",".join(self.__choice_param.choices)}}}[=VALUE]'


def _register_plugin_commands(group: click.Group):
    plugin_hook = load_plugins()
    additional_commands = (c for g in plugin_hook.instawow_add_commands() for c in g)
    for command in additional_commands:
        group.add_command(command)
    return group


def defn_to_urn(defn: Defn) -> str:
    return f'{defn.source}:{defn.alias}'


def _parse_debug_option(
    _: click.Context, __: click.Parameter, value: float
) -> tuple[bool, bool, bool]:
    return (value > 0, value > 1, value > 2)


@_register_plugin_commands
@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option(__version__, prog_name=__spec__.parent)
@click.option(
    '--debug',
    '-d',
    count=True,
    help='Log incrementally more things.  Additive.',
    callback=_parse_debug_option,
)
@click.option(
    '--no-cache',
    is_flag=True,
    default=False,
    help='Disable the HTTP cache.',
)
@click.option(
    '--profile',
    '-p',
    default='__default__',
    help='Activate the specified profile.',
)
@click.pass_context
def cli(ctx: click.Context, **__: object) -> None:
    "Add-on manager for World of Warcraft."
    ctx.obj = _CtxObjWrapper(ctx)


main = logger.catch(reraise=True)(cli)


@overload
def _parse_into_defn(manager: _manager.Manager, value: str, *, raise_invalid: bool = True) -> Defn:
    ...


@overload
def _parse_into_defn(
    manager: _manager.Manager, value: list[str], *, raise_invalid: bool = True
) -> list[Defn]:
    ...


def _parse_into_defn(
    manager: _manager.Manager, value: str | list[str] | None, *, raise_invalid: bool = True
) -> Defn | list[Defn] | None:
    if value is None:
        return None

    if not isinstance(value, str):
        defns = (_parse_into_defn(manager, v, raise_invalid=raise_invalid) for v in value)
        return uniq(defns)

    pair = manager.pair_uri(value)
    if not pair:
        if raise_invalid:
            raise click.BadParameter(value)

        pair = ('*', value)
    return Defn(*pair)


def _parse_into_defn_and_extend_addons(ctx: click.Context, __: click.Parameter, value: list[str]):
    addons: list[Defn] = ctx.params.setdefault('addons', [])
    defns = _parse_into_defn(ctx.obj.manager, value)
    addons.extend(defns)


def _parse_into_defn_with_version_and_extend_addons(
    ctx: click.Context, __: click.Parameter, value: Sequence[tuple[str, str]]
):
    addons: list[Defn] = ctx.params.setdefault('addons', [])
    defns = _parse_into_defn(ctx.obj.manager, [d for _, d in value])
    addons.extend(map(Defn.with_version, defns, (v for v, _ in value)))


def _extend_strategies(strategy: Strategy, ctx: click.Context, __: click.Parameter, value: bool):
    strategies = ctx.params.setdefault('strategies', set())
    if value:
        strategies.add(strategy)


@cli.command
@click.argument(
    'addons', nargs=-1, expose_value=False, callback=_parse_into_defn_and_extend_addons
)
@click.option(
    '--version',
    expose_value=False,
    multiple=True,
    type=(str, str),
    callback=_parse_into_defn_with_version_and_extend_addons,
    metavar='<VERSION ADDON>',
    help='A version followed by an add-on definition.',
)
@click.option(
    '--any-flavour',
    expose_value=False,
    is_flag=True,
    default=False,
    callback=partial(_extend_strategies, Strategy.any_flavour),
    help='Ignore game flavour compatibility.  Global option.',
)
@click.option(
    '--any-release-type',
    expose_value=False,
    is_flag=True,
    default=False,
    callback=partial(_extend_strategies, Strategy.any_release_type),
    help='Ignore add-on stability.  Global option.',
)
@click.option('--replace', is_flag=True, default=False, help='Replace unreconciled add-ons.')
@click.pass_obj
def install(
    mw: _CtxObjWrapper,
    addons: Sequence[Defn],
    strategies: Set[Literal[Strategy.any_flavour, Strategy.any_release_type]],
    replace: bool,
) -> None:
    "Install add-ons."
    if not addons:
        raise click.UsageError('You must provide at least one of "ADDONS" or "--version"')

    if strategies:
        addons = [
            evolve(a, strategies=evolve(a.strategies, **{s: True for s in strategies}))
            for a in addons
        ]

    results = mw.run_with_progress(mw.manager.install(addons, replace))
    Report(results.items()).generate_and_exit()


@cli.command
@click.argument('addons', nargs=-1, callback=_with_manager(_parse_into_defn))
@click.pass_obj
def update(mw: _CtxObjWrapper, addons: Sequence[Defn]) -> None:
    "Update installed add-ons."
    import sqlalchemy as sa

    def filter_results(result: R.ManagerResult):
        # Hide packages from output if they are up to date
        # and ``update`` was invoked without args,
        # provided that they are not pinned
        if addons or not isinstance(result, R.PkgUpToDate):
            return True
        else:
            return result.is_pinned

    def installed_pkgs_to_defns():
        with mw.manager.database.connect() as connection:
            return [
                models.Pkg.from_row_mapping(connection, p).to_defn()
                for p in connection.execute(sa.select(db.pkg)).mappings().all()
            ]

    results = mw.run_with_progress(mw.manager.update(addons or installed_pkgs_to_defns(), False))
    Report(results.items(), filter_results).generate_and_exit()


@cli.command
@click.argument('addons', nargs=-1, required=True, callback=_with_manager(_parse_into_defn))
@click.option(
    '--keep-folders',
    is_flag=True,
    default=False,
    help='Do not delete the add-on folders.',
)
@click.pass_obj
def remove(mw: _CtxObjWrapper, addons: Sequence[Defn], keep_folders: bool) -> None:
    "Remove add-ons."
    results = mw.run_with_progress(mw.manager.remove(addons, keep_folders))
    Report(results.items()).generate_and_exit()


@cli.command
@click.argument('addon', callback=_with_manager(_parse_into_defn))
@click.option(
    '--version',
    help='Version to roll back to.',
)
@click.option(
    '--undo',
    is_flag=True,
    default=False,
    help='Undo rollback by reinstalling an add-on using the default strategy.',
)
@click.pass_obj
def rollback(mw: _CtxObjWrapper, addon: Defn, version: str | None, undo: bool) -> None:
    "Roll an add-on back to an older version."
    from ._cli_prompts import Choice, ask, select

    if version and undo:
        raise click.UsageError('Cannot use "--version" with "--undo"')

    pkg = mw.manager.get_pkg(addon)
    if not pkg:
        Report([(addon, R.PkgNotInstalled())]).generate_and_exit()
    elif Strategy.version_eq not in mw.manager.resolvers[pkg.source].metadata.strategies:
        Report([(addon, R.PkgStrategiesUnsupported({Strategy.version_eq}))]).generate_and_exit()
    elif undo:
        Report(mw.run_with_progress(mw.manager.update([addon], True)).items()).generate_and_exit()

    reconstructed_defn = pkg.to_defn()
    if version:
        selection = version
    else:
        versions = pkg.logged_versions
        if len(versions) <= 1:
            Report([(addon, R.PkgFilesMissing('cannot find older versions'))]).generate_and_exit()

        choices = [
            Choice(
                [('', v.version)],
                value=v.version,
                disabled='installed version' if v.version == pkg.version else None,
            )
            for v in versions
        ]
        selection = ask(
            select(f'Select version of {defn_to_urn(reconstructed_defn)} for rollback', choices)
        )

    Report(
        mw.run_with_progress(
            mw.manager.update([reconstructed_defn.with_version(selection)], True)
        ).items()
    ).generate_and_exit()


@cli.command
@click.option('--auto', '-a', is_flag=True, default=False, help='Do not ask for user input.')
@click.option(
    '--installed',
    'rereconcile',
    is_flag=True,
    default=False,
    help='Re-reconcile installed add-ons.',
)
@click.option(
    '--list-unreconciled', is_flag=True, default=False, help='List unreconciled add-ons and exit.'
)
@click.pass_obj
def reconcile(mw: _CtxObjWrapper, auto: bool, rereconcile: bool, list_unreconciled: bool) -> None:
    "Reconcile pre-installed add-ons."
    from ._cli_prompts import PkgChoice, ask, confirm, select, skip
    from .matchers import DEFAULT_MATCHERS, AddonFolder, get_unreconciled_folders

    def construct_choice(pkg: models.Pkg, highlight_version: bool, disabled: bool):
        defn = pkg.to_defn()
        return PkgChoice(
            [
                ('', f'{defn_to_urn(defn)}=='),
                ('class:highlight-sub' if highlight_version else '', pkg.version),
            ],
            pkg=pkg,
            value=defn,
            disabled=disabled,
        )

    def gather_selections(
        groups: Collection[tuple[_T, Sequence[Defn]]],
        selector: Callable[[_T, Sequence[models.Pkg]], Defn | None],
    ):
        results = mw.run_with_progress(mw.manager.resolve(uniq(d for _, b in groups for d in b)))
        for addons_or_pkg, defns in groups:
            shortlist = [r for d in defns for r in (results[d],) if isinstance(r, models.Pkg)]
            if shortlist:
                selection = selector(addons_or_pkg, shortlist)
                yield selection
            else:
                yield None

    if rereconcile:
        if auto:
            raise click.UsageError('Cannot use "--auto" with "--installed"')

        import sqlalchemy as sa

        def select_alternative_pkg(installed_pkg: models.Pkg, pkgs: Sequence[models.Pkg]):
            highlight_version = not all_eq(i.version for i in (installed_pkg, *pkgs))
            choices = [
                construct_choice(installed_pkg, highlight_version, True),
                *(construct_choice(p, highlight_version, False) for p in pkgs),
                skip,
            ]
            selection = ask(select(installed_pkg.name, choices))
            return selection or None

        with mw.manager.database.connect() as connection:
            installed_pkgs = [
                models.Pkg.from_row_mapping(connection, p)
                for p in connection.execute(
                    sa.select(db.pkg).order_by(sa.func.lower(db.pkg.c.name))
                )
                .mappings()
                .all()
            ]

        groups = mw.run_with_progress(mw.manager.find_equivalent_pkg_defns(installed_pkgs))
        selections = [
            (p, s)
            for (p, _), s in zip(
                groups.items(), gather_selections(groups.items(), select_alternative_pkg)
            )
            if s
        ]
        if selections and ask(confirm('Install selected add-ons?')):
            Report(
                mw.run_with_progress(
                    mw.manager.remove([p.to_defn() for p, _ in selections], False),
                ).items()
            ).generate()
            Report(
                mw.run_with_progress(
                    mw.manager.install([s for _, s in selections], False),
                ).items()
            ).generate_and_exit()

    else:
        PREAMBLE = textwrap.dedent(
            '''\
            Use the arrow keys to navigate, <o> to open an add-on in your browser,
            enter to make a selection and <s> to skip to the next item.

            Versions that differ from the installed version or differ between
            choices are highlighted in purple.

            instawow will perform three passes in decreasing order of accuracy,
            looking to match source IDs and add-on names in TOC files, and folders.

            Selected add-ons will be reinstalled.

            You can also run `reconcile` in automatic mode by passing
            the `--auto` flag.  In this mode, add-ons will be reconciled
            without user input.
            '''
        )

        leftovers = get_unreconciled_folders(mw.manager)
        if list_unreconciled:
            table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
            click.echo(tabulate(table_rows))
            return
        elif not leftovers:
            click.echo('No add-ons left to reconcile.')
            return

        if not auto:
            click.echo(PREAMBLE)

        def select_pkg(addons: Sequence[AddonFolder], pkgs: Sequence[models.Pkg]):
            def combine_names():
                return textwrap.shorten(', '.join(a.name for a in addons), 60)

            # Highlight version if there's multiple of them
            highlight_version = not all_eq(i.version for i in chain(addons, pkgs))
            choices = [
                *(construct_choice(p, highlight_version, False) for p in pkgs),
                skip,
            ]
            selection = ask(select(f'{combine_names()} [{addons[0].version or "?"}]', choices))
            return selection or None

        def pick_first_pkg(addons: Sequence[AddonFolder], pkgs: Sequence[models.Pkg]):
            return pkgs[0].to_defn()

        select_pkg_ = pick_first_pkg if auto else select_pkg
        confirm_install = (
            (lambda: True) if auto else (lambda: ask(confirm('Install selected add-ons?')))
        )

        for fn in DEFAULT_MATCHERS.values():
            groups = mw.run_with_progress(fn(mw.manager, leftovers))
            selections = [s for s in gather_selections(groups, select_pkg_) if s is not None]
            if selections and confirm_install():
                results = mw.run_with_progress(mw.manager.install(selections, True))
                Report(results.items()).generate()

            leftovers = get_unreconciled_folders(mw.manager)
            if not leftovers:
                break

        if leftovers:
            click.echo()
            table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
            click.echo(tabulate(table_rows))


def _concat_search_terms(_: click.Context, __: click.Parameter, value: tuple[str, ...]):
    return ' '.join(value)


def _parse_iso_date_into_datetime(_: click.Context, __: click.Parameter, value: str | None):
    if value is not None:
        return datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=timezone.utc)


@cli.command
@click.argument('search-terms', nargs=-1, required=True, callback=_concat_search_terms)
@click.option(
    '--limit',
    '-l',
    default=10,
    type=click.IntRange(1, 20, clamp=True),
    help='A number to limit results to.',
)
@click.option(
    '--start-date',
    callback=_parse_iso_date_into_datetime,
    help='Omit results before this date.',
    metavar='YYYY-MM-DD',
)
@click.option(
    '--source',
    'sources',
    multiple=True,
    help='A source to search in.  Repeatable.',
)
@click.pass_context
def search(
    ctx: click.Context,
    search_terms: str,
    limit: int,
    sources: Sequence[str],
    start_date: datetime | None,
) -> None:
    "Search for add-ons to install."
    from ._cli_prompts import PkgChoice, ask, checkbox, confirm

    mw: _CtxObjWrapper = ctx.obj

    entries = mw.run_with_progress(
        mw.manager.search(search_terms, limit, frozenset(sources), start_date)
    )
    defns = [Defn(e.source, e.id) for e in entries]
    pkgs = (
        (evolve(d, alias=r.slug), r)
        for d, r in mw.run_with_progress(mw.manager.resolve(defns)).items()
        if isinstance(r, models.Pkg)
    )
    choices = [PkgChoice(f'{p.name}  ({defn_to_urn(d)}=={p.version})', d, pkg=p) for d, p in pkgs]
    if choices:
        selections: list[Defn] = ask(checkbox('Select add-ons to install', choices=choices))
        if selections and ask(confirm('Install selected add-ons?')):
            ctx.invoke(install, addons=selections, strategies=frozenset(), replace=False)
    else:
        click.echo('No results found.')


class _ListFormat(StrEnum):
    simple = enum.auto()
    detailed = enum.auto()
    json = enum.auto()


@cli.command('list')
@click.argument(
    'addons', nargs=-1, callback=_with_manager(partial(_parse_into_defn, raise_invalid=False))
)
@click.option(
    '--format',
    '-f',
    'output_format',
    type=_StrEnumChoiceParam(_ListFormat),
    default=_ListFormat.simple,
    show_default=True,
    help='Change the output format.',
)
@click.pass_obj
def list_installed(mw: _CtxObjWrapper, addons: Sequence[Defn], output_format: _ListFormat) -> None:
    "List installed add-ons."
    import sqlalchemy as sa

    with mw.manager.database.connect() as connection:

        def format_deps(pkg: models.Pkg):
            return (
                defn_to_urn(Defn(pkg.source, s or e.id))
                for e in pkg.deps
                for s in (
                    connection.execute(
                        sa.select(db.pkg.c.slug).filter_by(source=pkg.source, id=e.id)
                    ).scalar_one_or_none(),
                )
            )

        def row_mappings_to_pkgs():
            return map(models.Pkg.from_row_mapping, repeat(connection), pkg_mappings)

        pkg_mappings = (
            connection.execute(
                (
                    sa.select(db.pkg).filter(
                        sa.or_(
                            *(
                                db.pkg.c.slug.contains(d.alias)
                                if d.source == '*'
                                else (db.pkg.c.source == d.source)
                                & ((db.pkg.c.id == d.alias) | (db.pkg.c.slug == d.alias))
                                for d in addons
                            )
                        )
                    )
                    if addons
                    else sa.select(db.pkg)
                ).order_by(db.pkg.c.source, sa.func.lower(db.pkg.c.name))
            )
            .mappings()
            .all()
        )

        if output_format is _ListFormat.json:
            from cattrs.preconf.json import (
                make_converter,  # pyright: ignore[reportUnknownVariableType]
            )

            json_converter = make_converter()
            click.echo(
                json_converter.dumps(  # pyright: ignore[reportUnknownMemberType]
                    row_mappings_to_pkgs(),
                    list[models.Pkg],
                    indent=2,
                )
            )

        elif output_format is _ListFormat.detailed:
            formatter = click.HelpFormatter(max_width=99)
            for pkg in row_mappings_to_pkgs():
                with formatter.section(defn_to_urn(pkg.to_defn())):
                    formatter.write_dl(
                        [
                            ('name', pkg.name),
                            ('description', textwrap.shorten(pkg.description, 280)),
                            ('url', pkg.url),
                            ('version', pkg.version),
                            ('date_published', pkg.date_published.isoformat(' ', 'minutes')[:-6]),
                            ('folders', ', '.join(f.name for f in pkg.folders)),
                            ('deps', ', '.join(format_deps(pkg))),
                            (
                                'options',
                                '\n'.join(f'{s}={v}' for s, v in asdict(pkg.options).items()),
                            ),
                        ]
                    )
            click.echo(formatter.getvalue(), nl=False)

        else:
            click.echo(
                ''.join(f'{defn_to_urn(Defn(p["source"], p["slug"]))}\n' for p in pkg_mappings),
                nl=False,
            )


@cli.command(hidden=True)
@click.argument('addon', callback=_with_manager(partial(_parse_into_defn, raise_invalid=False)))
@click.pass_context
def info(ctx: click.Context, addon: Defn) -> None:
    "Alias of `list -f detailed`."
    ctx.invoke(list_installed, addons=(addon,), output_format=_ListFormat.detailed)


@cli.command
@click.argument('addon', callback=_with_manager(partial(_parse_into_defn, raise_invalid=False)))
@click.pass_obj
def reveal(mw: _CtxObjWrapper, addon: Defn) -> None:
    "Bring an add-on up in your file manager."
    pkg = mw.manager.get_pkg(addon, partial_match=True)
    if pkg:
        reveal_folder(mw.manager.config.addon_dir / pkg.folders[0].name)
    else:
        Report([(addon, R.PkgNotInstalled())]).generate_and_exit()


@cli.command
@click.argument(
    'addon', callback=_with_manager(partial(_parse_into_defn, raise_invalid=False)), required=False
)
@click.option(
    '--convert/--no-convert',
    default=True,
    show_default=True,
    help='Convert HTML and Markdown changelogs to plain text using pandoc.',
)
@click.pass_obj
def view_changelog(mw: _CtxObjWrapper, addon: Defn | None, convert: bool) -> None:
    """View the changelog of an installed add-on.

    If `addon` is not provided, displays the changelogs of all add-ons
    to have been installed within one minute of the last add-on.
    """

    MAX_LINES = 100

    def make_converter():
        import shutil

        pandoc = shutil.which('pandoc')
        if pandoc is None:

            def noop_convert(source: str, changelog: str):
                return changelog

            return noop_convert
        else:

            def real_convert(source: str, changelog: str):
                import subprocess

                changelog_format = mw.manager.resolvers[source].metadata.changelog_format
                if changelog_format not in {ChangelogFormat.html, ChangelogFormat.markdown}:
                    return changelog
                else:
                    return subprocess.check_output(
                        [pandoc, '-f', changelog_format, '-t', 'plain'], input=changelog, text=True
                    )

            return real_convert

    def format_combined_changelog_entry(source: str, slug: str, changelog: str):
        lines = changelog.splitlines()
        body = '\n'.join(
            (
                *(f'  {i}' for i in lines[:MAX_LINES]),
                *(('  [...]',) if len(lines) > MAX_LINES else ()),
            )
        )
        return f'{defn_to_urn(Defn(source, slug))}:\n{body}'

    if addon:
        pkg = mw.manager.get_pkg(addon, partial_match=True)
        if pkg:
            changelog = mw.run_with_progress(
                mw.manager.get_changelog(pkg.source, pkg.changelog_url)
            )
            if convert:
                changelog = make_converter()(pkg.source, changelog)
            click.echo_via_pager(changelog)
        else:
            Report([(addon, R.PkgNotInstalled())]).generate_and_exit()

    else:
        import sqlalchemy as sa

        with mw.manager.database.connect() as connection:
            join_clause = (db.pkg.c.source == db.pkg_version_log.c.pkg_source) & (
                db.pkg.c.id == db.pkg_version_log.c.pkg_id
            )
            last_installed_changelog_urls = connection.execute(
                sa.select(db.pkg.c.source, db.pkg.c.slug, db.pkg.c.changelog_url)
                .join(db.pkg_version_log, join_clause)
                .filter(
                    db.pkg_version_log.c.install_time
                    >= sa.select(
                        sa.func.datetime(
                            sa.func.max(db.pkg_version_log.c.install_time), '-1 minute'
                        )
                    )
                    .join(db.pkg, join_clause)
                    .scalar_subquery()
                )
            ).all()

        changelogs = mw.run_with_progress(
            gather(
                mw.manager.get_changelog(m.source, m.changelog_url)
                for m in last_installed_changelog_urls
            )
        )
        if convert:
            do_convert = make_converter()
            changelogs = (
                do_convert(m.source, c) for m, c in zip(last_installed_changelog_urls, changelogs)
            )

        click.echo_via_pager(
            '\n\n'.join(
                format_combined_changelog_entry(m.source, m.slug, c)
                for m, c in zip(last_installed_changelog_urls, changelogs)
            )
        )


def _show_active_config(ctx: click.Context, __: click.Parameter, value: bool):
    if value:
        click.echo(ctx.obj.manager.config.encode_for_display())
        ctx.exit()


async def _github_oauth_flow():
    from .github_auth import get_codes, poll_for_access_token

    async with init_web_client(None) as web_client:
        codes = await get_codes(web_client)
        click.echo(f'Navigate to {codes["verification_uri"]} and paste the code below:')
        click.echo(f'  {codes["user_code"]}')
        click.echo('Waiting...')
        access_token = await poll_for_access_token(
            web_client, codes['device_code'], codes['interval']
        )
        return access_token


class _EditableConfigOptions(StrEnum):
    AddonDir = 'addon_dir'
    GameFlavour = 'game_flavour'
    AutoUpdateCheck = 'global_config.auto_update_check'
    GithubAccessToken = 'global_config.access_tokens.github'
    CfcoreAccessToken = 'global_config.access_tokens.cfcore'
    WagoAddonsAccessToken = 'global_config.access_tokens.wago_addons'

    path: tuple[str, ...]

    def __new__(cls, value: str) -> Self:
        self = str.__new__(cls, value)
        self.path = tuple(value.split('.'))
        return self


@cli.command
@click.option(
    '--show-active',
    is_flag=True,
    default=False,
    expose_value=False,
    is_eager=True,
    callback=_show_active_config,
    help='Show the active configuration and exit.',
)
@click.argument(
    'editable-config-values',
    nargs=-1,
    type=_ManyOptionalChoiceValueParam(
        _StrEnumChoiceParam(_EditableConfigOptions),
        value_types={
            _EditableConfigOptions.AutoUpdateCheck: click.types.BoolParamType(),
        },
    ),
)
@click.pass_context
def configure(
    ctx: click.Context,
    editable_config_values: Mapping[_EditableConfigOptions, Any],
) -> Config:
    """Configure instawow.

    You can pass configuration keys as arguments to reconfigure an existing
    profile.  Pass a value to bypass the interactive prompt.  For example:

    \b
    * ``configure addon_dir`` will initiate an interactive session
      with autocompletion
    * ``configure "addon_dir=~/foo"` will set ``addon_dir``'s value
      to ``~/foo`` directly
    """
    from ._cli_prompts import AttrsFieldValidator, ask, confirm, password, path, select
    from .common import infer_flavour_from_path

    profile = ctx.find_root().params['profile']

    existing_global_config = GlobalConfig.read()

    config_values: dict[str, Any] | None = None
    try:
        config_values = asdict(Config.read(existing_global_config, profile))
    except FileNotFoundError:
        pass
    except Exception:
        logger.exception('unable to read existing config')

    if config_values is None:
        config_values = {'profile': profile, 'global_config': asdict(existing_global_config)}

    editable_config_values = dict(editable_config_values)
    if not editable_config_values:
        default_keys = {
            _EditableConfigOptions.AddonDir,
            _EditableConfigOptions.GameFlavour,
        }
        if existing_global_config.access_tokens.github is None:
            default_keys.add(_EditableConfigOptions.GithubAccessToken)

        editable_config_values = dict.fromkeys(default_keys)

    interactive_editable_config_keys = {k for k, v in editable_config_values.items() if v is None}

    if _EditableConfigOptions.AddonDir in interactive_editable_config_keys:
        editable_config_values[_EditableConfigOptions.AddonDir] = ask(
            path(
                'Add-on directory:',
                only_directories=True,
                validate=AttrsFieldValidator(
                    fields(resolve_types(Config)).addon_dir,
                    config_converter,
                ),
            )
        )

    if _EditableConfigOptions.GameFlavour in interactive_editable_config_keys:
        editable_config_values[_EditableConfigOptions.GameFlavour] = ask(
            select(
                'Game flavour:',
                choices=list(Flavour),
                initial_choice=config_values.get('addon_dir')
                and infer_flavour_from_path(config_values['addon_dir']),
            )
        )

    if _EditableConfigOptions.AutoUpdateCheck in interactive_editable_config_keys:
        editable_config_values[_EditableConfigOptions.AutoUpdateCheck] = ask(
            confirm('Periodically check for instawow updates?')
        )

    if _EditableConfigOptions.GithubAccessToken in interactive_editable_config_keys and ask(
        confirm('Set up GitHub authentication?')
    ):
        editable_config_values[_EditableConfigOptions.GithubAccessToken] = asyncio.run(
            _github_oauth_flow()
        )

    if _EditableConfigOptions.CfcoreAccessToken in interactive_editable_config_keys:
        click.echo(
            textwrap.fill(
                'An access token is required to use CurseForge. '
                'Log in to https://console.curseforge.com/ to generate an access token.'
            )
        )
        editable_config_values[_EditableConfigOptions.CfcoreAccessToken] = (
            ask(password('CFCore access token:')) or None
        )

    if _EditableConfigOptions.WagoAddonsAccessToken in interactive_editable_config_keys:
        click.echo(
            textwrap.fill(
                'An access token is required to use Wago Addons. '
                'Wago issues tokens to Patreon subscribers above a certain tier. '
                'See https://addons.wago.io/patreon for more information.'
            )
        )
        editable_config_values[_EditableConfigOptions.WagoAddonsAccessToken] = (
            ask(password('Wago Addons access token:')) or None
        )

    for key, value in editable_config_values.items():
        parent = config_values
        for part in key.path[:-1]:
            parent = parent[part]
        parent[key.path[-1]] = value

    config = config_converter.structure(config_values, Config)
    config.global_config.write()
    config.write()

    click.echo('Configuration written to:')
    click.echo(f'  {config.global_config.config_file}')
    click.echo(f'  {config.config_file}')

    return config


@cli.group('weakauras-companion')
def _weakauras_group() -> None:
    "Manage your WeakAuras."


@_weakauras_group.command('build')
@click.pass_obj
def build_weakauras_companion(mw: _CtxObjWrapper) -> None:
    "Build the WeakAuras Companion add-on."
    from .wa_updater import WaCompanionBuilder

    mw.run_with_progress(WaCompanionBuilder(mw.manager).build())


@_weakauras_group.command('list')
@click.pass_obj
def list_installed_wago_auras(mw: _CtxObjWrapper) -> None:
    "List WeakAuras installed from Wago."
    from .wa_updater import WaCompanionBuilder

    aura_groups = WaCompanionBuilder(mw.manager).extract_installed_auras()
    installed_auras = sorted(
        (g.addon_name, a.id, a.url)
        for g in aura_groups
        for v in g.root.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('type', 'name', 'URL'), *installed_auras]))


@cli.command(hidden=True)
@click.option(
    '--start-date',
    callback=_parse_iso_date_into_datetime,
    help='Omit results before this date.',
    metavar='YYYY-MM-DD',
)
def generate_catalogue(start_date: datetime | None) -> None:
    "Generate the master catalogue."
    import json

    from .cataloguer import BaseCatalogue, catalogue_converter

    catalogue = asyncio.run(BaseCatalogue.collate(start_date))
    catalogue_json = catalogue_converter.unstructure(catalogue)
    catalogue_path = Path(f'base-catalogue-v{catalogue.version}.json').resolve()
    catalogue_path.write_text(
        json.dumps(catalogue_json, indent=2),
        encoding='utf-8',
    )
    catalogue_path.with_suffix(f'.compact{catalogue_path.suffix}').write_text(
        json.dumps(catalogue_json, separators=(',', ':')),
        encoding='utf-8',
    )


@cli.command
@click.pass_context
def gui(ctx: click.Context) -> None:
    "Fire up the GUI."
    from instawow_gui.app import InstawowApp

    global_config = GlobalConfig.read().ensure_dirs()
    dummy_jsonrpc_config = Config.make_dummy_config(
        global_config=global_config, profile='__jsonrpc__'
    ).ensure_dirs()

    params = ctx.find_root().params
    setup_logging(dummy_jsonrpc_config.logging_dir, *params['debug'])

    InstawowApp(
        debug=any(params['debug']), version=__version__
    ).main_loop()  # pyright: ignore[reportUnknownMemberType]
