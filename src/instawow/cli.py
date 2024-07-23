from __future__ import annotations

import datetime as dt
import enum
import textwrap
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from functools import cached_property, partial, reduce
from itertools import chain, count, repeat
from typing import TYPE_CHECKING, Any, Generic, NoReturn, TypeVar, overload

import attrs
import click
import click.types
from typing_extensions import Self

from . import _logging, pkg_management, pkg_models, shared_ctx
from . import config as _config
from . import results as R
from ._utils.compat import StrEnum
from ._utils.iteration import all_eq, bucketise, uniq
from .definitions import ChangelogFormat, Defn, Strategy
from .plugins import get_plugin_commands

_T = TypeVar('_T')
_TStrEnum = TypeVar('_TStrEnum', bound=StrEnum)


class Report:
    SUCCESS_SYMBOL = click.style('✓', fg='green')
    FAILURE_SYMBOL = click.style('✗', fg='red')
    WARNING_SYMBOL = click.style('!', fg='blue')

    def __init__(
        self,
        results: Iterable[tuple[Defn, R.Result]],
        filter_fn: Callable[[R.Result], bool] = lambda _: True,
    ) -> None:
        self.results = list(results)
        self.filter_fn = filter_fn

    @property
    def exit_code(self) -> int:
        return any(
            isinstance(r, R.ManagerError | R.InternalError) and self.filter_fn(r)
            for _, r in self.results
        )

    @classmethod
    def _result_type_to_symbol(cls, result: R.Result) -> str:
        match result:
            case R.InternalError():
                return cls.WARNING_SYMBOL
            case R.ManagerError():
                return cls.FAILURE_SYMBOL
            case _:
                return cls.SUCCESS_SYMBOL

    def __str__(self) -> str:
        return '\n'.join(
            f'{self._result_type_to_symbol(r)} {click.style(a.as_uri(), bold=True)}\n'
            f'{textwrap.fill(r.message, initial_indent=" " * 2, subsequent_indent=" " * 4)}'
            for a, r in self.results
            if self.filter_fn(r)
        )

    def generate(self) -> None:
        config_ctx: ConfigBoundCtxProxy | None = click.get_current_context().obj
        if config_ctx and config_ctx.config.global_config.auto_update_check:
            from ._version_check import is_outdated

            outdated, new_version = run_with_progress(is_outdated(config_ctx.config.global_config))
            if outdated:
                click.echo(f'{self.WARNING_SYMBOL} instawow v{new_version} is available')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self) -> NoReturn:
        self.generate()
        ctx = click.get_current_context()
        ctx.exit(self.exit_code)


if TYPE_CHECKING:
    ConfigBoundCtxProxyBase = shared_ctx.ConfigBoundCtx
else:
    ConfigBoundCtxProxyBase = object


class ConfigBoundCtxProxy(ConfigBoundCtxProxyBase):
    def __init__(self, click_ctx: click.Context) -> None:
        self.__click_ctx = click_ctx

    if not TYPE_CHECKING:

        @cached_property
        def __config_ctx(self) -> shared_ctx.ConfigBoundCtx:
            global_config = _config.GlobalConfig.read().ensure_dirs()
            try:
                config = _config.ProfileConfig.read(
                    global_config, self.__click_ctx.params['profile']
                ).ensure_dirs()
            except FileNotFoundError:
                config = self.__click_ctx.invoke(configure)

            _logging.setup_logging(config.logging_dir, *self.__click_ctx.params['verbose'])

            return self.__click_ctx.with_resource(shared_ctx.ConfigBoundCtx(config))

        def __getattr__(self, name: str) -> Any:
            return getattr(self.__config_ctx, name)


def run_with_progress(awaitable: Awaitable[_T], click_ctx: click.Context | None = None) -> _T:
    import asyncio

    from .http import init_web_client

    if click_ctx is None:
        click_ctx = click.get_current_context()
    click_ctx = click_ctx.find_root()

    config_ctx: ConfigBoundCtxProxy = click_ctx.obj

    make_init_web_client = partial(
        init_web_client,
        config_ctx.config.global_config.http_cache_dir,
        no_cache=click_ctx.params['no_cache'],
    )

    if any(click_ctx.params['verbose']):

        async def run():
            async with make_init_web_client() as web_client:
                shared_ctx.web_client_var.set(web_client)
                return await awaitable

    else:
        from ._cli_prompts import ProgressBar, make_progress_bar_group
        from ._progress_reporting import make_progress_receiver
        from ._utils.aio import cancel_tasks
        from .pkg_archives._download import PkgDownloadProgress

        async def run():
            with (
                make_progress_receiver[PkgDownloadProgress]() as iter_progress,
                make_progress_bar_group() as progress_bar_group,
            ):

                async def observe_progress():
                    progress_bars = dict[int, ProgressBar]()

                    try:
                        async for progress_group in iter_progress:
                            for progress_id in progress_bars.keys() - progress_group.keys():
                                del progress_bars[progress_id]

                            for progress_id, progress in (
                                (k, progress_group[k])
                                for k in progress_bars.keys() ^ progress_group.keys()
                            ):
                                match progress:
                                    case {'type_': 'pkg_download', 'defn': defn}:
                                        label = f'Downloading {defn.as_uri()}'
                                    case {'label': str(label)}:
                                        pass
                                    case _:
                                        continue

                                progress_bars[progress_id] = ProgressBar(
                                    progress_bar=progress_bar_group,
                                    label=label,
                                    total=progress['total'],
                                    is_download=progress.get('unit') == 'bytes',
                                )

                            progress_bar_group.counters = list(progress_bars.values())

                            for progress_id, progress in progress_group.items():
                                progress_bars[progress_id].items_completed = progress['current']
                                progress_bar_group.invalidate()

                    finally:
                        progress_bar_group.counters = []

                observe_progress_task = asyncio.create_task(observe_progress())

                try:
                    async with make_init_web_client(with_progress=True) as web_client:
                        shared_ctx.web_client_var.set(web_client)
                        return await awaitable

                finally:
                    await cancel_tasks([observe_progress_task])

    return asyncio.run(run())


def _with_obj(fn: Callable[..., object]):
    def wrapper(ctx: click.Context, __: click.Parameter, value: object):
        return fn(ctx.obj, value)

    return wrapper


class _StrEnumChoiceParam(Generic[_TStrEnum], click.Choice):
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

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> _TStrEnum:
        converted_value = super().convert(value, param, ctx)
        return self.__choice_enum(converted_value)


class _ManyOptionalChoiceValueParam(click.types.CompositeParamType):
    name = 'optional-choice-value'

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
    additional_commands = (c for g in get_plugin_commands() for c in g)
    for command in additional_commands:
        group.add_command(command)
    return group


def _print_version(ctx: click.Context, __: click.Parameter, value: bool):
    if not value or ctx.resilient_parsing:
        return

    from ._version_check import get_version

    click.echo(f'{__spec__.parent}, version {get_version()}')
    ctx.exit()


def _parse_debug_option(
    _: click.Context, __: click.Parameter, value: float
) -> tuple[bool, bool, bool]:
    return (value > 0, value > 1, value > 2)


class _SectionedHelpGroup(click.Group):
    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        command_sections = bucketise(
            ((s, c) for s, c in self.commands.items() if not c.hidden),
            key=lambda c: 'Command groups' if isinstance(c[1], click.Group) else 'Commands',
        )
        if command_sections:
            for section_name, commands in command_sections.items():
                with formatter.section(section_name):
                    limit = formatter.width - 6 - max(len(s) for s, _ in commands)
                    formatter.write_dl(
                        [(s, c.get_short_help_str(limit)) for s, c in commands],
                    )


@overload
def _parse_uri(
    config_ctx: ConfigBoundCtxProxy,
    value: str,
    *,
    raise_invalid: bool = True,
) -> Defn: ...


@overload
def _parse_uri(
    config_ctx: ConfigBoundCtxProxy,
    value: list[str],
    *,
    raise_invalid: bool = True,
) -> list[Defn]: ...


def _parse_uri(
    config_ctx: ConfigBoundCtxProxy,
    value: str | list[str] | None,
    *,
    raise_invalid: bool = True,
) -> Defn | list[Defn] | None:
    if value is None:
        return None

    if not isinstance(value, str):
        defns = (_parse_uri(config_ctx, v, raise_invalid=raise_invalid) for v in value)
        return uniq(defns)

    try:
        defn = Defn.from_uri(value, known_sources=config_ctx.resolvers, allow_unsourced=True)
    except ValueError as exc:
        raise click.BadParameter(exc.args[0]) from None

    if not defn.source:
        match = pkg_management.get_alias_from_url(config_ctx, defn.alias)
        if match:
            source, alias = match
            defn = attrs.evolve(defn, source=source, alias=alias)
        elif raise_invalid and ':' not in defn.alias:
            raise click.BadParameter(value)

    return defn


def _make_pkg_where_clause_and_params(defns: Sequence[Defn]) -> tuple[str, dict[str, Any]]:
    def make_inner():
        iter_named_param = (f'where_param_{i}' for i in count())
        for defn, source_param, alias_param in zip(defns, iter_named_param, iter_named_param):
            if not defn.source:
                yield (
                    f"(pkg.slug LIKE '%' || :{alias_param} || '%')",
                    {alias_param: defn.alias},
                )
            elif not defn.alias:
                yield (
                    f'pkg.source = :{source_param}',
                    {source_param: defn.source},
                )
            else:
                yield (
                    f'pkg.source = :{source_param} AND (pkg.id = :{alias_param} OR lower(pkg.slug) = lower(:{alias_param}))',
                    {source_param: defn.source, alias_param: defn.alias},
                )

    if defns:
        where_clauses, where_params = zip(*make_inner())
        return (
            'WHERE\n  ' + '\n  OR '.join(where_clauses),
            reduce(lambda a, b: a | b, where_params, {}),
        )
    else:
        return ('', {})


class _ListFormat(StrEnum):
    Simple = enum.auto()
    Detailed = enum.auto()
    Json = enum.auto()


@click.group(context_settings={'help_option_names': ('-h', '--help')}, cls=_SectionedHelpGroup)
@click.option(
    '--version',
    callback=_print_version,
    is_flag=True,
    expose_value=False,
    is_eager=True,
    help='Show the version and exit',
)
@click.option(
    '--verbose',
    '-v',
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
    ctx.obj = ConfigBoundCtxProxy(ctx)


@cli.command
@click.argument('addons', nargs=-1, callback=_with_obj(_parse_uri))
@click.option(
    '--replace',
    'replace_folders',
    is_flag=True,
    default=False,
    help='Replace unreconciled add-ons.',
)
@click.option(
    '--dry-run',
    is_flag=True,
    default=False,
    help='Pretend to install add-ons.  Add-on archives will not be download and the '
    'database will not be modified.',
)
@click.pass_obj
def install(
    config_ctx: ConfigBoundCtxProxy,
    addons: Sequence[Defn],
    replace_folders: bool,
    dry_run: bool,
) -> None:
    "Install add-ons."
    results = run_with_progress(
        pkg_management.install(
            config_ctx, addons, replace_folders=replace_folders, dry_run=dry_run
        )
    )
    Report(results.items()).generate_and_exit()


@cli.command
@click.argument('addons', nargs=-1, callback=_with_obj(_parse_uri))
@click.option(
    '--dry-run',
    is_flag=True,
    default=False,
    help='Pretend to update add-ons.  Add-on archives will not be download and the '
    'database will not be modified.  Use this option to check for updates.',
)
@click.pass_obj
def update(
    config_ctx: ConfigBoundCtxProxy,
    addons: Sequence[Defn],
    dry_run: bool,
) -> None:
    "Update installed add-ons."

    def filter_results(result: R.Result):
        # Hide packages from output if they are up to date and not pinned.
        return True if addons or not isinstance(result, R.PkgUpToDate) else result.is_pinned

    results = run_with_progress(
        pkg_management.update(config_ctx, addons or 'all', dry_run=dry_run)
    )
    Report(results.items(), filter_results).generate_and_exit()


@cli.command
@click.argument('addons', nargs=-1, required=True, callback=_with_obj(_parse_uri))
@click.option(
    '--keep-folders',
    is_flag=True,
    default=False,
    help='Remove the add-on from the database but do not delete its folders.',
)
@click.pass_obj
def remove(config_ctx: ConfigBoundCtxProxy, addons: Sequence[Defn], keep_folders: bool) -> None:
    "Remove add-ons."
    results = run_with_progress(
        pkg_management.remove(config_ctx, addons, keep_folders=keep_folders)
    )
    Report(results.items()).generate_and_exit()


@cli.command
@click.argument('addon', callback=_with_obj(_parse_uri))
@click.option(
    '--undo',
    is_flag=True,
    default=False,
    help='Undo rollback by reinstalling an add-on using the default strategy.',
)
@click.pass_obj
def rollback(config_ctx: ConfigBoundCtxProxy, addon: Defn, undo: bool) -> None:
    "Roll an add-on back to an older version."
    from ._cli_prompts import Choice, select_one

    pkg = pkg_management.get_pkg(config_ctx, addon)
    if not pkg:
        Report([(addon, R.PkgNotInstalled())]).generate_and_exit()
    elif Strategy.VersionEq not in config_ctx.resolvers[pkg.source].metadata.strategies:
        Report([(addon, R.PkgStrategiesUnsupported({Strategy.VersionEq}))]).generate_and_exit()
    elif undo:
        Report(
            run_with_progress(
                pkg_management.update(config_ctx, [addon.with_default_strategy_set()])
            ).items()
        ).generate_and_exit()

    reconstructed_defn = pkg.to_defn()

    versions = pkg.logged_versions
    if len(versions) <= 1:
        Report([(addon, R.PkgFilesMissing('cannot find older versions'))]).generate_and_exit()

    choices = [
        Choice(v.version, value=v.version, disabled=v.version == pkg.version) for v in versions
    ]
    selection = select_one(
        f'Select version of {reconstructed_defn.as_uri()} for rollback', choices
    ).prompt()

    Report(
        run_with_progress(
            pkg_management.update(config_ctx, [reconstructed_defn.with_version(selection)])
        ).items()
    ).generate_and_exit()


@cli.command
@click.option('--auto', '-a', is_flag=True, default=False, help='Do not ask for user input.')
@click.option(
    '--list-unreconciled', is_flag=True, default=False, help='List unreconciled add-ons and exit.'
)
@click.pass_obj
def reconcile(config_ctx: ConfigBoundCtxProxy, auto: bool, list_unreconciled: bool) -> None:
    "Reconcile pre-installed add-ons."
    from ._cli_prompts import SKIP, Choice, confirm, select_one
    from ._utils.text import tabulate
    from .matchers import DEFAULT_MATCHERS, AddonFolder, get_unreconciled_folders

    leftovers = get_unreconciled_folders(config_ctx)
    if list_unreconciled and leftovers:
        click.echo(tabulate([('unreconciled',), *((f.name,) for f in sorted(leftovers))]))
        return
    elif not leftovers:
        click.echo('No add-ons left to reconcile.')
        return

    if not auto:
        click.echo(
            textwrap.dedent(
                """\
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
                """
            )
        )

    if auto:

        def confirm_install() -> bool:
            return True

        def select_pkg(
            addons: Sequence[AddonFolder], pkgs: Sequence[pkg_models.Pkg]
        ) -> Defn | None:
            return pkgs[0].to_defn()
    else:

        def confirm_install():
            return confirm('Install selected add-ons?').prompt()

        def select_pkg(addons: Sequence[AddonFolder], pkgs: Sequence[pkg_models.Pkg]):
            def construct_choice(pkg: pkg_models.Pkg, disabled: bool):
                defn = pkg.to_defn()
                return Choice(
                    [
                        ('', f'{defn.as_uri()}=='),
                        ('class:attention' if highlight_version else '', pkg.version),
                    ],
                    defn,
                    browser_url=pkg.url,
                    disabled=disabled,
                )

            # Highlight versions if they are disparate
            highlight_version = not all_eq(
                chain((a.toc_reader.version for a in addons), (p.version for p in pkgs))
            )

            selection = select_one(
                f'{textwrap.shorten(", ".join(a.name for a in addons), 60)}'
                f' [{addons[0].toc_reader.version or "?"}]',
                [construct_choice(p, False) for p in pkgs],
                can_skip=True,
            ).prompt()
            return selection if selection is not SKIP else None

    def gather_selections(
        groups: Collection[tuple[Sequence[AddonFolder], Sequence[Defn]]],
        pkgs: Mapping[Defn, pkg_models.Pkg],
    ):
        for addon_folder, defns in groups:
            shortlist = [p for d in defns for p in (pkgs.get(d),) if p]
            if shortlist:
                selection = select_pkg(addon_folder, shortlist)
                yield selection
            else:
                yield None

    for fn in DEFAULT_MATCHERS.values():
        defn_groups = run_with_progress(fn(config_ctx, leftovers))
        resolve_results = run_with_progress(
            pkg_management.resolve(config_ctx, uniq(d for _, b in defn_groups for d in b))
        )
        pkgs, _ = pkg_management.bucketise_results(resolve_results.items())

        selections = [s for s in gather_selections(defn_groups, pkgs) if s]
        if selections and confirm_install():
            results = run_with_progress(
                pkg_management.install(config_ctx, selections, replace_folders=True)
            )
            Report(results.items()).generate()

        leftovers = get_unreconciled_folders(config_ctx)
        if not leftovers:
            break

    if leftovers:
        click.echo()
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))


@cli.command
@click.argument('addons', nargs=-1, callback=_with_obj(partial(_parse_uri, raise_invalid=False)))
@click.pass_obj
def rereconcile(config_ctx: ConfigBoundCtxProxy, addons: Sequence[Defn]) -> None:
    "Rereconcile installed add-ons."
    from ._cli_prompts import SKIP, Choice, confirm, select_one

    def select_alternative_pkg(pkg: pkg_models.Pkg, equivalent_pkg_defns: Sequence[Defn]):
        def construct_choice(equivalent_pkg: pkg_models.Pkg, disabled: bool):
            defn = equivalent_pkg.to_defn()
            return Choice(
                [
                    ('', f'{defn.as_uri()}=='),
                    ('class:attention' if highlight_version else '', equivalent_pkg.version),
                ],
                defn,
                browser_url=equivalent_pkg.url,
                disabled=disabled,
            )

        shortlisted_pkgs = [p for d in equivalent_pkg_defns for p in (pkgs.get(d),) if p]
        if not shortlisted_pkgs:
            return None

        highlight_version = not all_eq(i.version for i in (pkg, *shortlisted_pkgs))

        selection = select_one(
            pkg.name,
            [
                construct_choice(pkg, True),
                *(construct_choice(p, False) for p in shortlisted_pkgs),
            ],
            can_skip=True,
        ).prompt()
        return selection if selection is not SKIP else None

    with config_ctx.database.connect() as connection:
        query = """
            SELECT *
            FROM pkg
            {where_clause}
            ORDER BY lower(name)
        """
        if addons:
            where_clause, query_params = _make_pkg_where_clause_and_params(addons)
            execute = partial(
                connection.execute, query.format(where_clause=where_clause), query_params
            )
        else:
            execute = partial(connection.execute, query.format(where_clause=''))

        installed_pkgs = [
            pkg_models.build_pkg_from_row_mapping(connection, p) for p in execute().fetchall()
        ]

    equivalent_pkg_defn_groups = run_with_progress(
        pkg_management.find_equivalent_pkg_defns(config_ctx, installed_pkgs)
    )
    resolve_results = run_with_progress(
        pkg_management.resolve(
            config_ctx, uniq(d for b in equivalent_pkg_defn_groups.values() for d in b)
        )
    )
    pkgs, _ = pkg_management.bucketise_results(resolve_results.items())

    selections = {
        p.to_defn(): s
        for p, d in equivalent_pkg_defn_groups.items()
        for s in (select_alternative_pkg(p, d),)
        if s
    }

    if selections and confirm('Install selected add-ons?').prompt():
        Report(
            run_with_progress(pkg_management.replace(config_ctx, selections)).items()
        ).generate_and_exit()


def _concat_search_terms(_: click.Context, __: click.Parameter, value: tuple[str, ...]):
    return ' '.join(value)


def _parse_iso_date_into_datetime(_: click.Context, __: click.Parameter, value: str | None):
    if value is not None:
        return dt.datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=dt.timezone.utc)


@cli.command
@click.argument('search-terms', nargs=-1, required=True, callback=_concat_search_terms)
@click.option(
    '--limit',
    '-l',
    default=10,
    show_default=True,
    type=click.IntRange(1, 20, clamp=True),
    help='Maximum results to return.',
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
    help='Search only in the specified source.  Multiple option.',
)
@click.option(
    '--prefer-source',
    help='Hide duplicates from other sources.',
)
@click.option(
    '--no-exclude-installed',
    is_flag=True,
    default=False,
    help='Do not exclude installed add-ons from search results.',
)
@click.pass_context
def search(
    ctx: click.Context,
    search_terms: str,
    limit: int,
    sources: Sequence[str],
    prefer_source: str | None,
    start_date: dt.datetime | None,
    no_exclude_installed: bool,
) -> None:
    "Search for add-ons to install."
    from ._cli_prompts import Choice, confirm, select_multiple
    from .catalogue.search import search

    catalogue_entries = run_with_progress(
        search(
            ctx.obj,
            search_terms,
            limit=limit,
            sources=frozenset(sources),
            prefer_source=prefer_source,
            start_date=start_date,
            filter_installed='ident' if no_exclude_installed else 'exclude_from_all_sources',
        ),
        ctx,
    )
    if catalogue_entries:
        choices = [
            Choice(f'{e.name}  ({d.as_uri()})', d, browser_url=e.url)
            for e in catalogue_entries
            for d in (Defn(e.source, e.slug or e.id, e.id),)
        ]
        selections = select_multiple('Select add-ons to install', choices=choices).prompt()
        if selections:
            if confirm('Install selected add-ons?').prompt():
                ctx.invoke(install, addons=selections, replace_folders=False, dry_run=False)
        else:
            click.echo(
                'Nothing was selected; select add-ons with <space>'
                ' and confirm by pressing <enter>.'
            )

    else:
        click.echo('No results found.')


@cli.command('list')
@click.argument('addons', nargs=-1, callback=_with_obj(partial(_parse_uri, raise_invalid=False)))
@click.option(
    '--format',
    '-f',
    'output_format',
    type=_StrEnumChoiceParam(_ListFormat),
    default=_ListFormat.Simple,
    show_default=True,
    help='Change the output format.',
)
@click.pass_obj
def list_installed(
    config_ctx: ConfigBoundCtxProxy, addons: Sequence[Defn], output_format: _ListFormat
) -> None:
    "List installed add-ons."

    with config_ctx.database.connect() as connection:
        where_clause, where_params = _make_pkg_where_clause_and_params(addons)
        pkg_mappings = connection.execute(
            f"""
                SELECT *
                FROM pkg
                {where_clause}
                ORDER BY source, lower(name)
            """,
            where_params,
        ).fetchall()

        def row_mappings_to_pkgs():
            return map(pkg_models.build_pkg_from_row_mapping, repeat(connection), pkg_mappings)

        match output_format:
            case _ListFormat.Json:
                from cattrs.preconf.json import make_converter

                click.echo(
                    make_converter().dumps(list(row_mappings_to_pkgs()), indent=2),
                )

            case _ListFormat.Detailed:

                def format_deps(pkg: pkg_models.Pkg):
                    return (
                        Defn(pkg.source, s or e.id).as_uri()
                        for e in pkg.deps
                        for (s,) in (
                            connection.execute(
                                'SELECT slug FROM pkg WHERE source = :source AND id = :id',
                                {'source': pkg.source, 'id': pkg.id},
                            ).fetchone(),
                        )
                    )

                formatter = click.HelpFormatter(max_width=99)

                for pkg in row_mappings_to_pkgs():
                    with formatter.section(pkg.to_defn().as_uri()):
                        formatter.write_dl(
                            [
                                ('name', pkg.name),
                                ('description', textwrap.shorten(pkg.description, 280)),
                                ('url', pkg.url),
                                ('version', pkg.version),
                                ('date published', pkg.date_published.astimezone().ctime()),
                                ('folders', ', '.join(f.name for f in pkg.folders)),
                                ('dependencies', ', '.join(format_deps(pkg))),
                                (
                                    'options',
                                    '; '.join(
                                        f'{s}={v!r}' for s, v in attrs.asdict(pkg.options).items()
                                    ),
                                ),
                            ]
                        )

                click.echo(formatter.getvalue(), nl=False)

            case _ListFormat.Simple:
                click.echo(
                    ''.join(f'{Defn(p["source"], p["slug"]).as_uri()}\n' for p in pkg_mappings),
                    nl=False,
                )


@cli.command(hidden=True)
@click.argument('addon', callback=_with_obj(partial(_parse_uri, raise_invalid=False)))
@click.pass_context
def info(ctx: click.Context, addon: Defn) -> None:
    "Alias of `list -f detailed`."
    ctx.invoke(list_installed, addons=(addon,), output_format=_ListFormat.Detailed)


@cli.command
@click.argument('addon', callback=_with_obj(partial(_parse_uri, raise_invalid=False)))
@click.pass_obj
def reveal(config_ctx: ConfigBoundCtxProxy, addon: Defn) -> None:
    "Bring an add-on up in your file manager."
    from ._utils.file import reveal_folder

    with config_ctx.database.connect() as connection:
        where_clause, where_params = _make_pkg_where_clause_and_params([addon])
        pkg_folder = connection.execute(
            f"""
                SELECT pkg_folder.name
                FROM pkg
                JOIN pkg_folder ON pkg.source = pkg_folder.pkg_source AND pkg.id = pkg_folder.pkg_id
                {where_clause}
                LIMIT 1
                """,
            where_params,
        ).fetchone()

        if pkg_folder:
            reveal_folder(config_ctx.config.addon_dir / pkg_folder['name'])
        else:
            Report([(addon, R.PkgNotInstalled())]).generate_and_exit()


@cli.command
@click.argument('addons', nargs=-1, callback=_with_obj(partial(_parse_uri, raise_invalid=False)))
@click.option(
    '--convert/--no-convert',
    default=True,
    show_default=True,
    help='Convert HTML and Markdown changelogs to plain text using pandoc. No-op if pandoc is not installed.',
)
@click.option(
    '--remote',
    is_flag=True,
    default=False,
    help='Fetch changelogs from sources.',
)
@click.pass_obj
def view_changelog(
    config_ctx: ConfigBoundCtxProxy, addons: Sequence[Defn], convert: bool, remote: bool
) -> None:
    """View installed and remote add-on changelogs.

    Invoked without arguments, it displays the changelogs of all add-ons
    to have been installed within one minute of the last add-on.

    By default, this command will only retrieve installed add-on changelogs.
    You can reverse this behaviour by passing `--remote`.  With `--remote`,
    you are also able to retrieve changelogs of older versions from sources
    which support the `version_eq` strategy, e.g. `github:foo/bar#version_eq=v1`.
    """

    from ._utils.aio import gather

    MAX_LINES = 100

    def make_converter():
        import shutil

        pandoc = shutil.which('pandoc')
        if pandoc is None:

            def noop_convert(source: str, changelog: str):
                return changelog

            return noop_convert
        else:
            import subprocess

            def real_convert(source: str, changelog: str):
                match config_ctx.resolvers[source].metadata.changelog_format:
                    case ChangelogFormat.Html:
                        pandoc_input_format = 'html'
                    case ChangelogFormat.Markdown:
                        # The "markdown" format will treat a list without a preceding
                        # empty line as a paragraph, which breaks the changelog
                        # of at least one popular add-on.
                        pandoc_input_format = 'commonmark'
                    case _:
                        return changelog

                return subprocess.check_output(
                    [pandoc, '-f', pandoc_input_format, '-t', 'plain'],
                    input=changelog,
                    text=True,
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
        return f'{Defn(source, slug).as_uri()}:\n{body}'

    if remote:
        pkgs, _ = pkg_management.bucketise_results(
            run_with_progress(pkg_management.resolve(config_ctx, addons)).items()
        )
        partial_pkgs = [pkg_models.make_db_converter().unstructure(p) for p in pkgs.values()]

    else:
        with config_ctx.database.connect() as connection:
            query = """
                SELECT pkg.source, pkg.slug, pkg.changelog_url
                FROM pkg
            """
            if addons:
                where_clause, query_params = _make_pkg_where_clause_and_params(addons)
                execute = partial(connection.execute, query + where_clause, query_params)
            else:
                query += """
                    JOIN pkg_version_log ON pkg.source = pkg_version_log.pkg_source AND pkg.id = pkg_version_log.pkg_id
                    WHERE pkg_version_log.install_time >= (
                        SELECT datetime(max(pkg_version_log.install_time), '-1 minute')
                        FROM pkg_version_log
                        JOIN pkg ON pkg.source = pkg_version_log.pkg_source AND pkg.id = pkg_version_log.pkg_id
                    )
                """
                execute = partial(connection.execute, query)

            partial_pkgs = execute().fetchall()

    changelogs = run_with_progress(
        gather(
            pkg_management.get_changelog(config_ctx, m['source'], m['changelog_url'])
            for m in partial_pkgs
        )
    )
    if convert:
        do_convert = make_converter()
        changelogs = (do_convert(m['source'], c) for m, c in zip(partial_pkgs, changelogs))

    output = '\n\n'.join(
        format_combined_changelog_entry(m['source'], m['slug'], c)
        for m, c in zip(partial_pkgs, changelogs)
    )
    if output:
        click.echo_via_pager(output)


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
        self._value_ = value
        self.path = tuple(value.split('.'))
        return self


@cli.command
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
) -> _config.ProfileConfig:
    """Configure instawow.

    You can pass configuration keys as arguments to reconfigure an existing
    profile.  Pass a value to suppress the interactive prompt.  For example:

    \b
    * ``configure addon_dir`` will initiate an interactive session
      with autocompletion
    * ``configure "addon_dir=~/foo"` will set ``addon_dir``'s value
      to ``~/foo`` immediately
    """
    import asyncio

    from ._cli_prompts import (
        SKIP,
        AttrsFieldValidator,
        Choice,
        confirm,
        password,
        path,
        select_one,
    )
    from .wow_installations import (
        ADDON_DIR_PARTS,
        Flavour,
        find_installations,
        infer_flavour_from_addon_dir,
    )

    profile = ctx.find_root().params['profile']

    existing_global_config = _config.GlobalConfig.read()

    config_values: dict[str, Any] | None = None
    try:
        config_values = attrs.asdict(_config.ProfileConfig.read(existing_global_config, profile))
    except FileNotFoundError:
        pass
    except Exception:
        _logging.logger.exception('unable to read existing config')

    is_new_profile = config_values is None
    if is_new_profile:
        config_values = {'profile': profile, 'global_config': attrs.asdict(existing_global_config)}

    editable_config_values = dict(editable_config_values)
    if not editable_config_values:
        default_keys = {_EditableConfigOptions.AddonDir, _EditableConfigOptions.GameFlavour}
        if existing_global_config.access_tokens.github is None:
            default_keys |= {_EditableConfigOptions.GithubAccessToken}

        editable_config_values = dict.fromkeys(default_keys)

    interactive_editable_config_keys = {k for k, v in editable_config_values.items() if v is None}
    if interactive_editable_config_keys:
        # 0 = Unconfigured
        # 1 = `addon_dir` configured
        # 2 = both `addon_dir` and `game_flavour` configured
        installation_configured = 0
        if (
            is_new_profile
            and {_EditableConfigOptions.AddonDir, _EditableConfigOptions.GameFlavour}
            <= interactive_editable_config_keys
        ):
            known_installations = list(existing_global_config.iter_installations())
            unimported_installations = [
                (k, v and v['flavour'])
                for k, v in find_installations()
                if not any(d.samefile(k) for d in known_installations)
            ]
            if unimported_installations:
                selection = select_one(
                    'Installation',
                    [Choice(f'{k}  [{v}]', (k, v)) for k, v in unimported_installations],
                    can_skip=True,
                ).prompt()
                if selection is not SKIP:
                    (installation_path, flavour) = selection

                    addon_dir = installation_path.joinpath(*ADDON_DIR_PARTS)
                    addon_dir.mkdir(exist_ok=True)

                    editable_config_values |= {
                        _EditableConfigOptions.AddonDir: addon_dir,
                        _EditableConfigOptions.GameFlavour: flavour,
                    }
                    installation_configured = 2 if flavour else 1

        if (
            installation_configured == 0
            and _EditableConfigOptions.AddonDir in interactive_editable_config_keys
        ):
            editable_config_values[_EditableConfigOptions.AddonDir] = path(
                'Add-on directory',
                only_directories=True,
                validator=AttrsFieldValidator(
                    attrs.fields(attrs.resolve_types(_config.ProfileConfig)).addon_dir,
                    _config.config_converter,
                ),
            ).prompt()

        if (
            installation_configured < 2
            and _EditableConfigOptions.GameFlavour in interactive_editable_config_keys
        ):
            editable_config_values[_EditableConfigOptions.GameFlavour] = select_one(
                'Game flavour',
                [Choice(f, f) for f in Flavour if not f.is_retired],
                initial_value=config_values.get('addon_dir')
                and infer_flavour_from_addon_dir(config_values['addon_dir']),
            ).prompt()

        if _EditableConfigOptions.AutoUpdateCheck in interactive_editable_config_keys:
            editable_config_values[_EditableConfigOptions.AutoUpdateCheck] = confirm(
                'Periodically check for instawow updates?'
            ).prompt()

        if _EditableConfigOptions.GithubAccessToken in interactive_editable_config_keys:
            click.echo(
                textwrap.fill(
                    'Generating an access token for GitHub is recommended '
                    'to avoid being rate limited.  You may only perform 60 '
                    'requests an hour without an access token.'
                )
            )
            if confirm('Set up GitHub authentication?').prompt():
                from .github_auth import get_codes, poll_for_access_token
                from .http import init_web_client

                async def github_oauth_flow():
                    async with init_web_client(None) as web_client:
                        codes = await get_codes(web_client)
                        click.echo(
                            f'Navigate to {codes["verification_uri"]} and paste the code below:'
                        )
                        click.echo(f'  {codes["user_code"]}')
                        click.echo('Waiting...')
                        access_token = await poll_for_access_token(
                            web_client, codes['device_code'], codes['interval']
                        )
                        return access_token

                editable_config_values[_EditableConfigOptions.GithubAccessToken] = asyncio.run(
                    asyncio.wait_for(github_oauth_flow(), timeout=60 * 5)
                )

        if _EditableConfigOptions.CfcoreAccessToken in interactive_editable_config_keys:
            click.echo(
                textwrap.fill(
                    'An API key is required to use CurseForge. '
                    'Log in to CurseForge for Studios <https://console.curseforge.com/> '
                    'to generate a key.'
                )
            )
            editable_config_values[_EditableConfigOptions.CfcoreAccessToken] = (
                password('CurseForge API key:').prompt() or None
            )

        if _EditableConfigOptions.WagoAddonsAccessToken in interactive_editable_config_keys:
            click.echo(
                textwrap.fill(
                    'An access token is required to use Wago Addons. '
                    'Wago issues tokens to Patreon <https://addons.wago.io/patreon> '
                    'subscribers above a certain tier.'
                )
            )
            editable_config_values[_EditableConfigOptions.WagoAddonsAccessToken] = (
                password('Wago Addons access token:').prompt() or None
            )

    for key, value in editable_config_values.items():
        parent = config_values
        for part in key.path[:-1]:
            parent = parent[part]
        parent[key.path[-1]] = value

    config = _config.ProfileConfig.from_values(config_values)
    config.global_config.write()
    config.write()

    click.echo('Configuration written to:')
    click.echo(f'  {config.global_config.config_file}')
    click.echo(f'  {config.config_file}')

    return config


@cli.group('debug')
def _debug_group():
    "Retrieve debugging information."


@_debug_group.command('config')
@click.pass_obj
def debug_config(config_ctx: ConfigBoundCtxProxy) -> None:
    "Print the active configuration."
    import json

    click.echo(json.dumps(config_ctx.config.unstructure_for_display(), indent=2))


@_debug_group.command('sources')
@click.pass_obj
def debug_sources(config_ctx: ConfigBoundCtxProxy) -> None:
    "Print active source metadata."
    from cattrs.preconf.json import make_converter

    json_converter = make_converter()

    click.echo(json_converter.dumps([r.metadata for r in config_ctx.resolvers.values()], indent=2))


@_register_plugin_commands
@cli.group('plugins')
def _plugin_group() -> None:  # pyright: ignore[reportUnusedFunction]
    "Registered plug-ins."


@cli.command(hidden=True)
@click.option(
    '--start-date',
    callback=_parse_iso_date_into_datetime,
    help='Omit results before this date.',
    metavar='YYYY-MM-DD',
)
def generate_catalogue(start_date: dt.datetime | None) -> None:
    "Generate the master catalogue."
    import asyncio
    import json
    from pathlib import Path

    from ._sources import DEFAULT_RESOLVERS
    from .catalogue.cataloguer import Catalogue, catalogue_converter

    catalogue = asyncio.run(
        Catalogue.collate((r.catalogue for r in DEFAULT_RESOLVERS), start_date)
    )
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


main = cli
