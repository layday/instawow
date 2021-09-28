from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Generator, Iterable, Iterator, Sequence, Set
from contextlib import contextmanager
from datetime import datetime
from enum import Enum
from functools import partial, wraps
import importlib.util
from itertools import chain
from pathlib import Path
import textwrap
from typing import Any, NoReturn, TypeVar, overload

import click

from . import __version__, _deferred_types, db
from . import manager as _manager
from . import models
from . import results as R
from .common import Strategy
from .config import Config, Flavour, setup_logging
from .plugins import load_plugins
from .resolvers import ChangelogFormat, Defn
from .utils import cached_property, gather, is_outdated, make_progress_bar, tabulate, uniq

_T = TypeVar('_T')
_F = TypeVar('_F', bound='Callable[..., object]')


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
            f'{self._result_type_to_symbol(r)} {click.style(a.to_urn(), bold=True)}\n'
            f'{textwrap.fill(r.message, initial_indent=" " * 2, subsequent_indent=" " * 4)}'
            for a, r in self.results
            if self.filter_fn(r)
        )

    def generate(self) -> None:
        manager_wrapper: ManagerWrapper | None = click.get_current_context().obj
        if manager_wrapper and manager_wrapper.manager.config.auto_update_check:
            outdated, new_version = run_with_progress(is_outdated())
            if outdated:
                click.echo(f'{self.WARNING_SYMBOL} instawow-{new_version} is available')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self) -> NoReturn:
        self.generate()
        ctx: click.Context = click.get_current_context()
        ctx.exit(self.exit_code)


def _init_cli_web_client(
    progress_bar: _deferred_types.prompt_toolkit.shortcuts.ProgressBar,
    tickers: set[asyncio.Task[None]],
) -> _deferred_types.aiohttp.ClientSession:
    from aiohttp import TraceConfig, hdrs
    from prompt_toolkit.shortcuts import ProgressBarCounter

    TICK_INTERVAL = 0.1

    async def do_on_request_end(
        client_session: _deferred_types.aiohttp.ClientSession,
        trace_config_ctx: Any,
        params: _deferred_types.aiohttp.TraceRequestEndParams,
    ):
        trace_request_ctx: _manager.TraceRequestCtx = trace_config_ctx.trace_request_ctx
        if trace_request_ctx:
            response = params.response
            label = (
                'Downloading '
                + Defn(trace_request_ctx['pkg'].source, trace_request_ctx['pkg'].slug).to_urn()
                if trace_request_ctx['report_progress'] == 'pkg_download'
                else trace_request_ctx['label']
            )
            # The encoded size is not exposed in the aiohttp streaming API
            # so we cannot display progress.  When the total is ``None``
            # the progress bar is animated as being "indeterminate"
            total = None if hdrs.CONTENT_ENCODING in response.headers else response.content_length

            async def ticker():
                counter: ProgressBarCounter[None] = ProgressBarCounter(
                    progress_bar=progress_bar, label=label, total=total
                )
                progress_bar.counters.append(counter)
                try:
                    while not response.content.is_eof():
                        counter.items_completed = response.content.total_bytes
                        progress_bar.invalidate()
                        await asyncio.sleep(TICK_INTERVAL)
                finally:
                    progress_bar.counters.remove(counter)

            tickers.add(asyncio.create_task(ticker()))

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return _manager.init_web_client(trace_configs=[trace_config])


@contextmanager
def _cancel_tickers() -> Iterator[set[asyncio.Task[None]]]:
    tickers: set[asyncio.Task[None]] = set()
    try:
        yield tickers
    finally:
        for ticker in tickers:
            ticker.cancel()


def run_with_progress(awaitable: Awaitable[_T]) -> _T:
    async def run():
        with _cancel_tickers() as tickers, make_progress_bar() as progress_bar:
            async with _init_cli_web_client(progress_bar, tickers) as web_client:
                _manager.Manager.contextualise(web_client=web_client)
                return await awaitable

    return asyncio.run(run())


def _override_asyncio_loop_policy() -> None:
    # The proactor event loop which became the default loop on Windows
    # in Python 3.8 is causing issues with aiohttp.
    # See https://github.com/aio-libs/aiohttp/issues/4324
    policy = getattr(asyncio, 'WindowsSelectorEventLoopPolicy', None)
    if policy:
        asyncio.set_event_loop_policy(policy())


def _apply_patches() -> None:
    _override_asyncio_loop_policy()


class ManagerWrapper:
    def __init__(self, ctx: click.Context) -> None:
        self.ctx = ctx

    @cached_property
    def manager(self) -> _manager.Manager:
        try:
            config = Config.read(self.ctx.params['profile']).ensure_dirs()
        except FileNotFoundError:
            config = self.ctx.invoke(configure, promptless=False)

        setup_logging(config, self.ctx.params['log_level'], self.ctx.params['log_to_stderr'])

        manager = _manager.Manager.from_config(config)
        self.ctx.call_on_close(manager.database.close)
        return manager

    @staticmethod
    def pass_manager(fn: _F) -> _F:
        @wraps(fn)
        def wrapper(*args: object, **kwargs: object):
            return fn(click.get_current_context().obj.manager, *args, **kwargs)

        return wrapper  # type: ignore


def _with_manager(
    fn: Callable[..., object]
) -> Callable[[click.Context, click.Parameter, object], object]:
    def wrapper(ctx: click.Context, __: click.Parameter, value: object):
        return fn(ctx.obj.manager, value)

    return wrapper


class EnumParam(click.Choice):
    def __init__(
        self,
        choice_enum: type[Enum],
        excludes: Set[Enum] = frozenset(),
        case_sensitive: bool = True,
    ) -> None:
        self.choice_enum = choice_enum
        super().__init__(
            choices=[c.name for c in choice_enum if c not in excludes],
            case_sensitive=case_sensitive,
        )

    def convert(
        self, value: str, param: click.Parameter | None, ctx: click.Context | None
    ) -> Enum:
        parent_result = super().convert(value, param, ctx)
        return self.choice_enum[parent_result]


def _register_plugin_commands(group: click.Group) -> click.Group:
    plugin_hook = load_plugins()
    additional_commands = (c for g in plugin_hook.instawow_add_commands() for c in g)
    for command in additional_commands:
        group.add_command(command)
    return group


def _set_log_level(_: click.Context, __: click.Parameter, value: bool) -> str:
    return 'DEBUG' if value else 'INFO'


@_register_plugin_commands
@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.version_option(__version__, prog_name=__package__)
@click.option(
    '--debug',
    'log_level',
    is_flag=True,
    default=False,
    callback=_set_log_level,
    help='Log more things.',
)
@click.option(
    '--log-to-stderr',
    is_flag=True,
    default=False,
    help='Log to stderr for development.',
    hidden=True,
)
@click.option(
    '--profile',
    '-p',
    default='__default__',
    help='Activate the specified profile.',
)
@click.pass_context
def main(ctx: click.Context, log_level: str, log_to_stderr: bool, profile: str) -> None:
    "Add-on manager for World of Warcraft."
    _apply_patches()
    ctx.obj = ManagerWrapper(ctx)


@overload
def parse_into_defn(manager: _manager.Manager, value: str, *, raise_invalid: bool = True) -> Defn:
    ...


@overload
def parse_into_defn(
    manager: _manager.Manager, value: list[str], *, raise_invalid: bool = True
) -> list[Defn]:
    ...


@overload
def parse_into_defn(manager: _manager.Manager, value: None, *, raise_invalid: bool = True) -> None:
    ...


def parse_into_defn(
    manager: _manager.Manager, value: str | list[str] | None, *, raise_invalid: bool = True
) -> Defn | list[Defn] | None:
    if value is None:
        return None

    if not isinstance(value, str):
        defns = (parse_into_defn(manager, v, raise_invalid=raise_invalid) for v in value)
        return uniq(defns)

    pair = manager.pair_uri(value)
    if not pair:
        if raise_invalid:
            raise click.BadParameter(value)

        pair = ('*', value)
    return Defn(*pair)


def parse_into_defn_with_strategy(
    manager: _manager.Manager, value: Sequence[tuple[Strategy, str]]
) -> Iterator[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    return map(lambda d, s: d.with_(strategy=s), defns, (s for s, _ in value))


def parse_into_defn_with_version(
    manager: _manager.Manager, value: Sequence[tuple[str, str]]
) -> Iterator[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    return map(Defn.with_version, defns, (v for v, _ in value))


def _combine_addons(
    fn: Callable[[_manager.Manager, object], Iterable[Defn]],
    ctx: click.Context,
    __: click.Parameter,
    value: object,
) -> None:
    addons: list[Defn] = ctx.params.setdefault('addons', [])
    if value:
        addons.extend(fn(ctx.obj.manager, value))


_EXCLUDED_STRATEGIES = frozenset({Strategy.default, Strategy.version})


@main.command()
@click.argument(
    'addons', nargs=-1, callback=partial(_combine_addons, parse_into_defn), expose_value=False
)
@click.option(
    '--with-strategy',
    '-s',
    multiple=True,
    type=(EnumParam(Strategy, _EXCLUDED_STRATEGIES), str),
    expose_value=False,
    callback=partial(_combine_addons, parse_into_defn_with_strategy),
    metavar='<STRATEGY ADDON>...',
    help='A strategy followed by an add-on definition.  '
    'The strategy is one of: '
    f'{", ".join(s for s in Strategy if s not in _EXCLUDED_STRATEGIES)}.',
)
@click.option(
    '--version',
    multiple=True,
    type=(str, str),
    expose_value=False,
    callback=partial(_combine_addons, parse_into_defn_with_version),
    metavar='<VERSION ADDON>...',
    help='A version followed by an add-on definition.',
)
@click.option('--replace', is_flag=True, default=False, help='Replace unreconciled add-ons.')
@ManagerWrapper.pass_manager
def install(manager: _manager.Manager, addons: Sequence[Defn], replace: bool) -> None:
    "Install add-ons."
    if not addons:
        raise click.UsageError(
            'You must provide at least one of "ADDONS", "--with-strategy" or "--version"'
        )

    results = run_with_progress(manager.install(addons, replace))
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, callback=_with_manager(parse_into_defn))
@ManagerWrapper.pass_manager
def update(manager: _manager.Manager, addons: Sequence[Defn]) -> None:
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

    update_defns = addons or [
        Defn(**v)
        for v in manager.database.execute(
            sa.select(
                db.pkg.c.source,
                db.pkg.c.id,
                db.pkg.c.slug.label('alias'),
                db.pkg.c.version,
                db.pkg_options.c.strategy,
            ).join(db.pkg_options)
        )
        .mappings()
        .all()
    ]
    results = run_with_progress(manager.update(update_defns, False))
    Report(results.items(), filter_results).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=_with_manager(parse_into_defn))
@click.option(
    '--keep-folders',
    is_flag=True,
    default=False,
    help="Do not delete the add-on folders.",
)
@ManagerWrapper.pass_manager
def remove(manager: _manager.Manager, addons: Sequence[Defn], keep_folders: bool) -> None:
    "Remove add-ons."
    results = run_with_progress(manager.remove(addons, keep_folders))
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addon', callback=_with_manager(parse_into_defn))
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
@ManagerWrapper.pass_manager
def rollback(manager: _manager.Manager, addon: Defn, version: str | None, undo: bool) -> None:
    "Roll an add-on back to an older version."
    from .prompts import Choice, select

    if version and undo:
        raise click.UsageError('Cannot use "--version" and "--undo" together')

    pkg = manager.get_pkg(addon)
    if not pkg:
        report: Report = Report([(addon, R.PkgNotInstalled())])
        report.generate_and_exit()

    if Strategy.version not in manager.resolvers[pkg.source].strategies:
        Report([(addon, R.PkgStrategyUnsupported(Strategy.version))]).generate_and_exit()

    if undo:
        Report(run_with_progress(manager.update([addon], True)).items()).generate_and_exit()

    reconstructed_defn = Defn.from_pkg(pkg)
    if version:
        selection = version
    else:
        versions = pkg.logged_versions
        if len(versions) <= 1:
            Report(
                [(addon, R.PkgFileUnavailable('cannot find older versions'))]
            ).generate_and_exit()

        choices = [
            Choice(
                [('', v.version)],
                value=v.version,
                disabled='installed version' if v.version == pkg.version else None,
            )
            for v in versions
        ]
        selection = select(
            f'Select version of {reconstructed_defn.to_urn()} for rollback', choices
        ).unsafe_ask()

    Report(
        run_with_progress(
            manager.update([reconstructed_defn.with_version(selection)], True)
        ).items()
    ).generate_and_exit()


@main.command()
@click.option(
    '--auto', '-a', is_flag=True, default=False, help='Do not ask for user confirmation.'
)
@click.option(
    '--list-unreconciled', is_flag=True, default=False, help='List unreconciled add-ons and exit.'
)
@ManagerWrapper.pass_manager
def reconcile(manager: _manager.Manager, auto: bool, list_unreconciled: bool) -> None:
    "Reconcile pre-installed add-ons."
    from .matchers import (
        AddonFolder,
        get_unreconciled_folder_set,
        match_addon_names_with_folder_names,
        match_folder_name_subsets,
        match_toc_source_ids,
    )
    from .prompts import PkgChoice, confirm, select, skip

    preamble = textwrap.dedent(
        '''\
        Use the arrow keys to navigate, <o> to open an add-on in your browser,
        enter to make a selection and <s> to skip to the next item.

        Versions that differ from the installed version or differ between
        choices are highlighted in purple.

        The reconciler will perform three passes in decreasing order of accuracy,
        looking to match source IDs and add-on names in TOC files, and folders.

        Selected add-ons will be reinstalled.

        You can also run `reconcile` in promptless mode by passing
        the `--auto` flag.  In this mode, add-ons will be reconciled
        without user input.
        '''
    )

    def prompt_one(addons: list[AddonFolder], pkgs: list[models.Pkg]) -> Defn | tuple[()]:
        def construct_choice(pkg: models.Pkg):
            defn = Defn.from_pkg(pkg)
            title = [
                ('', f'{defn.to_urn()}=='),
                ('class:highlight-sub' if highlight_version else '', pkg.version),
            ]
            return PkgChoice(title, pkg=pkg, value=defn)

        # Highlight version if there's multiple of them
        highlight_version = len({i.version for i in chain(addons, pkgs)}) > 1
        choices = list(chain(map(construct_choice, pkgs), (skip,)))
        addon = addons[0]
        # Using 'unsafe_ask' to let ^C bubble up
        selection = select(f'{addon.name} [{addon.version or "?"}]', choices).unsafe_ask()
        return selection

    def prompt(groups: Sequence[tuple[list[AddonFolder], list[Defn]]]) -> Iterable[Defn]:
        uniq_defns = uniq(d for _, b in groups for d in b)
        results = run_with_progress(manager.resolve(uniq_defns))
        for addons, defns in groups:
            shortlist: list[models.Pkg] = list(filter(models.is_pkg, (results[d] for d in defns)))
            if shortlist:
                selection = Defn.from_pkg(shortlist[0]) if auto else prompt_one(addons, shortlist)
                selection and (yield selection)

    def match_all() -> Generator[list[Defn], frozenset[AddonFolder], None]:
        # Match in order of increasing heuristicitivenessitude
        for fn in (
            match_toc_source_ids,
            match_folder_name_subsets,
            match_addon_names_with_folder_names,
        ):
            groups = run_with_progress(fn(manager, (yield [])))
            yield list(prompt(groups))

    leftovers = get_unreconciled_folder_set(manager)
    if list_unreconciled:
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))
        return
    elif not leftovers:
        click.echo('No add-ons left to reconcile.')
        return

    if not auto:
        click.echo(preamble)

    matcher = match_all()
    for _ in matcher:  # Skip over consumer yields
        selections = matcher.send(leftovers)
        if selections and (auto or confirm('Install selected add-ons?').unsafe_ask()):
            results = run_with_progress(manager.install(selections, replace=True))
            Report(results.items()).generate()

        leftovers = get_unreconciled_folder_set(manager)

    if leftovers:
        click.echo()
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))


def _concat_search_terms(_: click.Context, __: click.Parameter, value: tuple[str, ...]) -> str:
    return ' '.join(value)


@main.command()
@click.argument('search-terms', nargs=-1, required=True, callback=_concat_search_terms)
@click.option(
    '--limit',
    '-l',
    default=10,
    type=click.IntRange(1, 20, clamp=True),
    help='A number to limit results to.',
)
@click.option(
    '--source',
    'sources',
    multiple=True,
    help='A source to search in.  Repeatable.',
)
@click.pass_context
def search(ctx: click.Context, search_terms: str, limit: int, sources: Sequence[str]) -> None:
    "Search for add-ons to install."
    from .prompts import PkgChoice, checkbox, confirm

    manager: _manager.Manager = ctx.obj.manager

    entries = run_with_progress(manager.search(search_terms, limit, frozenset(sources) or None))
    defns = [Defn(e.source, e.id) for e in entries]
    pkgs = (
        (d.with_(alias=r.slug), r)
        for d, r in run_with_progress(manager.resolve(defns)).items()
        if models.is_pkg(r)
    )
    choices = [PkgChoice(f'{p.name}  ({d.to_urn()}=={p.version})', d, pkg=p) for d, p in pkgs]
    if choices:
        selections = checkbox('Select add-ons to install', choices=choices).unsafe_ask()
        if selections and confirm('Install selected add-ons?').unsafe_ask():
            ctx.invoke(install, addons=selections)
    else:
        click.echo('No results found.')


class ListFormats(str, Enum):
    simple = 'simple'
    detailed = 'detailed'
    json = 'json'


@main.command('list')
@click.argument(
    'addons', nargs=-1, callback=_with_manager(partial(parse_into_defn, raise_invalid=False))
)
@click.option(
    '--format',
    '-f',
    'output_format',
    type=EnumParam(ListFormats),
    default=ListFormats.simple,
    show_default=True,
    help='Change the output format.',
)
@ManagerWrapper.pass_manager
def list_installed(
    manager: _manager.Manager, addons: Sequence[Defn], output_format: ListFormats
) -> None:
    "List installed add-ons."
    import sqlalchemy as sa

    def format_deps(pkg: models.Pkg):
        return (
            Defn(pkg.source, s or e.id).to_urn()
            for e in pkg.deps
            for s in (
                manager.database.execute(
                    sa.select(db.pkg.c.slug).filter_by(source=pkg.source, id=e.id)
                ).scalar_one_or_none(),
            )
        )

    pkgs = [
        models.Pkg.from_row_mapping(manager.database, p)
        for p in manager.database.execute(
            sa.select(db.pkg)
            .filter(
                sa.or_(
                    *(
                        db.pkg.c.slug.contains(d.alias)
                        if d.source == '*'
                        else (db.pkg.c.source == d.source)
                        & ((db.pkg.c.id == d.alias) | (db.pkg.c.slug == d.alias))
                        for d in addons
                    )
                )
                if addons
                else True
            )
            .order_by(db.pkg.c.source, db.pkg.c.name)
        )
        .mappings()
        .all()
    ]
    if output_format is ListFormats.json:
        click.echo(models.PkgList.parse_obj(pkgs).json(indent=2))

    elif output_format is ListFormats.detailed:
        formatter = click.HelpFormatter(max_width=99)
        for pkg in pkgs:
            with formatter.section(Defn.from_pkg(pkg).to_urn()):
                formatter.write_dl(
                    [
                        ('name', pkg.name),
                        ('description', textwrap.shorten(pkg.description, 280)),
                        ('url', pkg.url),
                        ('version', pkg.version),
                        ('date_published', pkg.date_published.isoformat(' ', 'minutes')[:-6]),
                        ('folders', ', '.join(f.name for f in pkg.folders)),
                        ('deps', ', '.join(format_deps(pkg))),
                        ('options.strategy', pkg.options.strategy),
                    ]
                )
        click.echo(formatter.getvalue(), nl=False)

    else:
        click.echo(''.join(f'{Defn.from_pkg(p).to_urn()}\n' for p in pkgs), nl=False)


@main.command(hidden=True)
@click.argument('addon', callback=_with_manager(partial(parse_into_defn, raise_invalid=False)))
@click.pass_context
def info(ctx: click.Context, addon: Defn) -> None:
    "Alias of `list -f detailed`."
    ctx.invoke(list_installed, addons=(addon,), output_format=ListFormats.detailed)


@main.command()
@click.argument('addon', callback=_with_manager(partial(parse_into_defn, raise_invalid=False)))
@ManagerWrapper.pass_manager
def reveal(manager: _manager.Manager, addon: Defn) -> None:
    "Bring an add-on up in your file manager."
    pkg = manager.get_pkg(addon, partial_match=True)
    if pkg:
        click.launch(str(manager.config.addon_dir / pkg.folders[0].name), locate=True)
    else:
        Report([(addon, R.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument(
    'addon', callback=_with_manager(partial(parse_into_defn, raise_invalid=False)), required=False
)
@click.option(
    '--convert',
    is_flag=True,
    default=False,
    help='Convert output to plain text.  Requires pandoc.',
)
@ManagerWrapper.pass_manager
def view_changelog(manager: _manager.Manager, addon: Defn | None, convert: bool) -> None:
    "View the changelog of an installed add-on."

    def do_convert(source: str, changelog: str):
        import subprocess

        changelog_format = manager.resolvers[source].changelog_format
        if changelog_format not in {ChangelogFormat.html, ChangelogFormat.markdown}:
            return changelog
        else:
            return subprocess.check_output(
                ['pandoc', '-f', changelog_format, '-t', 'plain'], input=changelog, text=True
            )

    if addon:
        pkg = manager.get_pkg(addon, partial_match=True)
        if pkg:
            changelog = run_with_progress(manager.get_changelog(pkg.changelog_url))
            if convert:
                changelog = do_convert(pkg.source, changelog)
            click.echo_via_pager(changelog)
        else:
            Report([(addon, R.PkgNotInstalled())]).generate_and_exit()

    else:
        import sqlalchemy as sa

        last_installed_changelog_urls = manager.database.execute(
            sa.select(db.pkg.c.source, db.pkg.c.slug, db.pkg.c.changelog_url)
            .join(db.pkg_version_log)
            .filter(
                db.pkg_version_log.c.install_time
                >= sa.select(
                    sa.func.datetime(sa.func.max(db.pkg_version_log.c.install_time), '-1 minute')
                )
                .join(db.pkg)
                .scalar_subquery()
            )
        ).all()
        changelogs = run_with_progress(
            gather(manager.get_changelog(m.changelog_url) for m in last_installed_changelog_urls)
        )
        if convert:
            changelogs = (
                do_convert(m.source, c) for m, c in zip(last_installed_changelog_urls, changelogs)
            )
        click.echo_via_pager(
            '\n\n'.join(
                Defn(m.source, m.slug).to_urn() + ':\n' + textwrap.indent(c, '  ')
                for m, c in zip(last_installed_changelog_urls, changelogs)
            )
        )


def _show_active_config(ctx: click.Context, __: click.Parameter, value: bool) -> None:
    if value:
        click.echo(ctx.obj.manager.config.json(indent=2))
        ctx.exit()


@main.command()
@click.option(
    '--active',
    'show_active',
    is_flag=True,
    default=False,
    expose_value=False,
    is_eager=True,
    callback=_show_active_config,
    help='Show the active configuration and exit.',
)
@click.option(
    '--promptless',
    is_flag=True,
    default=False,
    help='Do not prompt for input and derive the configuration from the environment.',
)
@click.pass_context
def configure(ctx: click.Context, promptless: bool) -> Config:
    "Configure instawow."
    if promptless:
        make_config = Config
    else:
        from .prompts import PydanticValidator, path, select

        addon_dir = path(
            'Add-on directory:',
            only_directories=True,
            validate=PydanticValidator(Config, 'addon_dir'),
        ).unsafe_ask()
        game_flavour = select(
            'Game flavour:',
            choices=list(Flavour),
            initial_choice=Config.infer_flavour(addon_dir),
        ).unsafe_ask()
        make_config = partial(Config, addon_dir=addon_dir, game_flavour=game_flavour)

    config = make_config(profile=ctx.find_root().params['profile']).write()
    click.echo(f'Configuration written to: {config.config_file}')
    return config


@main.group('weakauras-companion')
def _weakauras_group() -> None:
    "Manage your WeakAuras."


@_weakauras_group.command('build')
@ManagerWrapper.pass_manager
def build_weakauras_companion(manager: _manager.Manager) -> None:
    "Build the WeakAuras Companion add-on."
    from .wa_updater import BuilderConfig, WaCompanionBuilder

    config = BuilderConfig()
    run_with_progress(WaCompanionBuilder(manager, config).build())


@_weakauras_group.command('list')
@ManagerWrapper.pass_manager
def list_installed_wago_auras(manager: _manager.Manager) -> None:
    "List WeakAuras installed from Wago."
    from .wa_updater import BuilderConfig, WaCompanionBuilder

    config = BuilderConfig()
    aura_groups = WaCompanionBuilder(manager, config).extract_installed_auras()
    installed_auras = sorted(
        (g.filename, textwrap.fill(a.id, width=30, max_lines=1), a.url)
        for g in aura_groups
        for v in g.__root__.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('in file', 'name', 'URL'), *installed_auras]))


def _parse_datetime(_: click.Context, __: click.Parameter, value: str | None) -> datetime | None:
    if value is not None:
        return datetime.fromisoformat(value)


@main.command(hidden=True)
@click.argument('filename', type=click.Path(dir_okay=False))
@click.option('--age-cutoff', callback=_parse_datetime)
def generate_catalogue(filename: str, age_cutoff: datetime | None) -> None:
    "Generate the master catalogue."
    from .resolvers import Catalogue

    catalogue = asyncio.run(Catalogue.collate(age_cutoff))
    file = Path(filename)
    file.write_text(
        catalogue.json(indent=2),
        encoding='utf-8',
    )
    file.with_suffix(f'.compact{file.suffix}').write_text(
        catalogue.json(separators=(',', ':')),
        encoding='utf-8',
    )


@main.command(hidden=importlib.util.find_spec('instawow_gui') is None)
@click.pass_context
def gui(ctx: click.Context) -> None:
    "Fire up the GUI."
    from instawow_gui.app import InstawowApp

    dummy_config = Config.get_dummy_config(profile='__jsonrpc__').ensure_dirs()
    params = ctx.find_root().params
    setup_logging(dummy_config, params['log_level'], params['log_to_stderr'])

    InstawowApp(version=__version__).main_loop()
