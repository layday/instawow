from __future__ import annotations

import contextvars
import datetime as dt
import enum
import textwrap
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from functools import partial, reduce
from itertools import chain, count, repeat
from typing import Any, Never, TypeVar, overload

import click

from .. import _logging, config_ctx, definitions, pkg_management
from .. import config as _config
from .. import results as _results
from ._helpers import ManyOptionalChoiceValueParam, SectionedHelpGroup, StrEnumChoiceParam

_T = TypeVar('_T')


class Report:
    SUCCESS_SYMBOL = click.style('✓', fg='green')
    FAILURE_SYMBOL = click.style('✗', fg='red')
    WARNING_SYMBOL = click.style('!', fg='blue')

    def __init__(
        self,
        results: Iterable[tuple[definitions.Defn, _results.Result]],
        filter_fn: Callable[[_results.Result], bool] = lambda _: True,
    ) -> None:
        self.results = list(results)
        self.filter_fn = filter_fn

    @property
    def exit_code(self) -> int:
        return any(
            isinstance(r, _results.ManagerError | _results.InternalError) and self.filter_fn(r)
            for _, r in self.results
        )

    @classmethod
    def _result_type_to_symbol(cls, result: _results.Result) -> str:
        match result:
            case _results.InternalError():
                return cls.WARNING_SYMBOL
            case _results.ManagerError():
                return cls.FAILURE_SYMBOL
            case _:
                return cls.SUCCESS_SYMBOL

    def __str__(self) -> str:
        return '\n'.join(
            f'{self._result_type_to_symbol(r)} {click.style(a.as_uri(), bold=True)}\n'
            f'{textwrap.fill(str(r), initial_indent=" " * 2, subsequent_indent=" " * 4)}'
            for a, r in self.results
            if self.filter_fn(r)
        )

    def generate(self) -> None:
        config = config_ctx.config()
        if config.global_config.auto_update_check:
            from .._version import is_outdated

            outdated, new_version = run_with_progress(is_outdated(config.global_config))
            if outdated:
                click.echo(f'{self.WARNING_SYMBOL} instawow v{new_version} is available')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self) -> Never:
        self.generate()
        click.get_current_context().exit(
            self.exit_code,
        )


def run_with_progress(awaitable: Awaitable[_T]) -> _T:
    import asyncio

    from .. import http_ctx
    from ..http import init_web_client

    click_ctx = click.get_current_context().find_root()

    make_init_web_client = partial(
        init_web_client,
        config_ctx.config().global_config.http_cache_dir,
        no_cache=click_ctx.params['no_cache'],
    )

    if any(click_ctx.params['verbosity']):

        async def run():
            async with make_init_web_client() as web_client:
                http_ctx.web_client.set(web_client)

                return await awaitable

    else:

        async def run():
            from contextlib import AsyncExitStack

            from .._progress_reporting import make_progress_receiver
            from .._utils.aio import cancel_tasks
            from ..pkg_archives._download import PkgDownloadProgress
            from ._prompts import make_progress_bar_group

            async with AsyncExitStack() as exit_stack:
                _, make_iter_progress = exit_stack.enter_context(
                    make_progress_receiver[PkgDownloadProgress]()
                )
                update_progress = exit_stack.enter_context(make_progress_bar_group())

                async def observe_progress():
                    async for progress_group in make_iter_progress():
                        update_progress(
                            {
                                i: {
                                    'label': f'Downloading {p["defn"].as_uri()}'
                                    if p['type_'] == 'pkg_download'
                                    else p['label'],
                                    'current': p['current'],
                                    'total': p['total'],
                                    'is_download': p.get('unit') == 'bytes',
                                }
                                for i, p in progress_group.items()
                                if 'label' in p
                            }
                        )

                exit_stack.push_async_callback(
                    cancel_tasks, [asyncio.create_task(observe_progress())]
                )

                http_ctx.web_client.set(
                    await exit_stack.enter_async_context(make_init_web_client(with_progress=True))
                )

                return await awaitable
            raise

    return asyncio.run(run())


def _register_plugin_commands(group: click.Group):
    from ..plugins import get_plugin_commands

    additional_commands = (c for g in get_plugin_commands() for c in g)
    for command in additional_commands:
        group.add_command(command)
    return group


def _print_version_option(click_ctx: click.Context, _click_param: click.Parameter, value: bool):
    if not value or click_ctx.resilient_parsing:
        return

    from .._version import get_version

    click.echo(f'instawow, version {get_version()}')
    click_ctx.exit()


def _parse_debug_option(
    _click_ctx: click.Context, _click_param: click.Parameter, value: float
) -> tuple[bool, bool, bool]:
    return (value > 0, value > 1, value > 2)


@overload
def _parse_uri_option(
    _click_ctx: click.Context,
    _click_param: click.Parameter,
    value: str,
    *,
    retain_unknown_source: bool = False,
    raise_invalid: bool = True,
) -> definitions.Defn: ...


@overload
def _parse_uri_option(
    _click_ctx: click.Context,
    _click_param: click.Parameter,
    value: list[str],
    *,
    retain_unknown_source: bool = False,
    raise_invalid: bool = True,
) -> list[definitions.Defn]: ...


def _parse_uri_option(
    _click_ctx: click.Context,
    _click_param: click.Parameter,
    value: str | list[str],
    *,
    retain_unknown_source: bool = False,
    raise_invalid: bool = True,
):
    import attrs

    from .._utils.iteration import uniq

    if not isinstance(value, str):
        defns = (
            _parse_uri_option(
                _click_ctx,
                _click_param,
                v,
                retain_unknown_source=retain_unknown_source,
                raise_invalid=raise_invalid,
            )
            for v in value
        )
        return uniq(defns)

    try:
        defn = definitions.Defn.from_uri(
            value,
            known_sources=config_ctx.resolvers(),
            retain_unknown_source=retain_unknown_source,
        )
    except ValueError as exc:
        raise click.BadParameter(exc.args[0]) from None

    if not defn.source:
        match = pkg_management.get_alias_from_url(defn.alias)
        if match:
            source, alias = match
            defn = attrs.evolve(defn, source=source, alias=alias)
        elif raise_invalid and ':' not in defn.alias:
            raise click.BadParameter(value)

    return defn


def _concat_search_terms_option(
    _click_ctx: click.Context, _click_param: click.Parameter, value: tuple[str, ...]
):
    return ' '.join(value)


def _parse_iso_date_into_datetime_option(
    _click_ctx: click.Context, _click_param: click.Parameter, value: str | None
):
    if value is not None:
        return dt.datetime.strptime(value, '%Y-%m-%d').replace(tzinfo=dt.UTC)


def _make_pkg_where_clause_and_params(
    defns: Sequence[definitions.Defn],
) -> tuple[str, dict[str, Any]]:
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
            reduce(lambda a, b: a | b, where_params, dict[str, Any]()),
        )
    else:
        return ('', {})


class _ListFormat(enum.StrEnum):
    Simple = enum.auto()
    Detailed = enum.auto()
    Json = enum.auto()


@click.group(context_settings={'help_option_names': ('-h', '--help')}, cls=SectionedHelpGroup)
@click.option(
    '--version',
    callback=_print_version_option,
    is_flag=True,
    expose_value=False,
    is_eager=True,
    help='Show the version and exit',
)
@click.option(
    '--verbose',
    '-v',
    'verbosity',
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
def cli(verbosity: tuple[bool, bool, bool], no_cache: bool, profile: str):
    "Add-on manager for World of Warcraft."

    global_config = _config.GlobalConfig.read().ensure_dirs()
    _logging.setup_logging(global_config.logging_dir, *verbosity, profile=profile)

    @config_ctx.config.set
    def _():
        try:
            return _config.ProfileConfig.read(global_config, profile).ensure_dirs()
        except _config.UninitialisedConfigError:
            return click.get_current_context().invoke(configure)


@cli.command
@click.argument('addons', nargs=-1, callback=_parse_uri_option)
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
def install(addons: Sequence[definitions.Defn], replace_folders: bool, dry_run: bool):
    "Install add-ons."

    results = run_with_progress(
        pkg_management.install(addons, replace_folders=replace_folders, dry_run=dry_run)
    )
    Report(results.items()).generate_and_exit()


@cli.command
@click.argument('addons', nargs=-1, callback=_parse_uri_option)
@click.option(
    '--dry-run',
    is_flag=True,
    default=False,
    help='Pretend to update add-ons.  Add-on archives will not be download and the '
    'database will not be modified.  Use this option to check for updates.',
)
def update(addons: Sequence[definitions.Defn], dry_run: bool):
    "Update installed add-ons."

    def filter_results(result: _results.Result):
        # Hide packages from output if they are up to date and not pinned.
        return True if addons or not isinstance(result, _results.PkgUpToDate) else result.is_pinned

    results = run_with_progress(pkg_management.update(addons or 'all', dry_run=dry_run))
    Report(results.items(), filter_results).generate_and_exit()


@cli.command
@click.argument(
    'addons',
    nargs=-1,
    required=True,
    callback=partial(_parse_uri_option, retain_unknown_source=True),
)
@click.option(
    '--keep-folders',
    is_flag=True,
    default=False,
    help='Remove the add-on from the database but do not delete its folders.',
)
def remove(addons: Sequence[definitions.Defn], keep_folders: bool):
    "Remove add-ons."
    results = run_with_progress(pkg_management.remove(addons, keep_folders=keep_folders))
    Report(results.items()).generate_and_exit()


@cli.command
@click.argument('addon', callback=_parse_uri_option)
@click.option(
    '--undo',
    is_flag=True,
    default=False,
    help='Undo rollback by reinstalling an add-on using the default strategy.',
)
def rollback(addon: definitions.Defn, undo: bool):
    "Roll an add-on back to an older version."
    from ..definitions import Strategy
    from ._prompts import Choice, select_one

    pkg = pkg_management.get_pkg(addon)
    if not pkg:
        Report([(addon, _results.PkgNotInstalled())]).generate_and_exit()
    elif Strategy.VersionEq not in config_ctx.resolvers()[pkg.source].metadata.strategies:
        Report(
            [(addon, _results.PkgStrategiesUnsupported({Strategy.VersionEq}))]
        ).generate_and_exit()
    elif undo:
        Report(
            run_with_progress(pkg_management.update([addon.with_default_strategy_set()])).items()
        ).generate_and_exit()

    reconstructed_defn = pkg.to_defn()

    versions = pkg.logged_versions
    if len(versions) <= 1:
        Report(
            [(addon, _results.PkgFilesMissing('cannot find older versions'))]
        ).generate_and_exit()

    choices = [
        Choice(v.version, value=v.version, disabled=v.version == pkg.version) for v in versions
    ]
    selection = select_one(
        f'Select version of {reconstructed_defn.as_uri()} for rollback', choices
    ).prompt()

    Report(
        run_with_progress(
            pkg_management.update([reconstructed_defn.with_version(selection)])
        ).items()
    ).generate_and_exit()


@cli.command
@click.option('--auto', '-a', is_flag=True, default=False, help='Do not ask for user input.')
@click.option(
    '--list-unreconciled', is_flag=True, default=False, help='List unreconciled add-ons and exit.'
)
def reconcile(auto: bool, list_unreconciled: bool):
    "Reconcile pre-installed add-ons."
    from .._utils.iteration import all_eq, uniq
    from .._utils.text import tabulate
    from ..matchers import DEFAULT_MATCHERS, AddonFolder, get_unreconciled_folders
    from ..resolvers import PkgCandidate
    from ._prompts import SKIP, Choice, confirm, select_one

    leftovers = get_unreconciled_folders()
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
            addons: Sequence[AddonFolder], pkg_candidates: Mapping[definitions.Defn, PkgCandidate]
        ) -> definitions.Defn | None:
            return next(iter(pkg_candidates))

    else:

        def confirm_install():
            return confirm('Install selected add-ons?').prompt()

        def select_pkg(
            addons: Sequence[AddonFolder], pkg_candidates: Mapping[definitions.Defn, PkgCandidate]
        ):
            # Highlight versions if they are disparate
            highlight_version = not all_eq(
                chain(
                    (a.toc_reader.version for a in addons),
                    (p['version'] for p in pkg_candidates.values()),
                )
            )

            selection = select_one(
                f'{textwrap.shorten(", ".join(a.name for a in addons), 60)}'
                f' [{addons[0].toc_reader.version or "?"}]',
                [
                    Choice(
                        [
                            ('', f'{d.as_uri()}=='),
                            ('class:attention' if highlight_version else '', p['version']),
                        ],
                        d,
                        browser_url=p['url'],
                    )
                    for d, p in pkg_candidates.items()
                ],
                can_skip=True,
            ).prompt()
            return selection if selection is not SKIP else None

    def gather_selections(
        groups: Collection[tuple[Sequence[AddonFolder], Sequence[definitions.Defn]]],
        pkg_candidates: Mapping[definitions.Defn, PkgCandidate],
    ):
        for addon_folder, defns in groups:
            shortlist = {
                definitions.Defn(o.source, p['slug'], p['id']): p
                for o in defns
                for p in (pkg_candidates.get(o),)
                if p
            }
            if shortlist:
                selection = select_pkg(addon_folder, shortlist)
                yield selection
            else:
                yield None

    for matcher_fn in DEFAULT_MATCHERS.values():
        defn_groups = run_with_progress(matcher_fn(leftovers))
        resolve_results = run_with_progress(
            pkg_management.resolve(uniq(d for _, b in defn_groups for d in b))
        )
        pkg_candidates, _ = pkg_management.bucketise_results(resolve_results.items())

        selections = [s for s in gather_selections(defn_groups, pkg_candidates) if s]
        if selections and confirm_install():
            results = run_with_progress(pkg_management.install(selections, replace_folders=True))
            Report(results.items()).generate()

        leftovers = get_unreconciled_folders()
        if not leftovers:
            break

    if leftovers:
        click.echo()
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))


@cli.command
@click.argument('addons', nargs=-1, callback=partial(_parse_uri_option, raise_invalid=False))
def rereconcile(addons: Sequence[definitions.Defn]):
    "Rereconcile installed add-ons."

    from .._utils.iteration import all_eq, uniq
    from ..pkg_db.models import Pkg, build_pkg_from_row_mapping
    from ._prompts import SKIP, Choice, confirm, select_one

    with config_ctx.database() as connection:
        query = """
            SELECT *
            FROM pkg
            {where_clause}
            ORDER BY lower(name)
        """
        if addons:
            where_clause, query_params = _make_pkg_where_clause_and_params(addons)
            execute_query = partial(
                connection.execute, query.format(where_clause=where_clause), query_params
            )
        else:
            execute_query = partial(connection.execute, query.format(where_clause=''))

        installed_pkgs = [
            build_pkg_from_row_mapping(connection, p) for p in execute_query().fetchall()
        ]

    equivalent_pkg_defn_groups = run_with_progress(
        pkg_management.find_equivalent_pkg_defns(installed_pkgs)
    )
    resolve_results = run_with_progress(
        pkg_management.resolve(uniq(d for b in equivalent_pkg_defn_groups.values() for d in b))
    )
    pkg_candidates, _ = pkg_management.bucketise_results(resolve_results.items())

    def select_alternative_pkg(pkg: Pkg, equivalent_defns: Sequence[definitions.Defn]):
        shortlisted_pkg_candidates = {
            definitions.Defn(d.source, p['slug'], p['id']): p
            for d in equivalent_defns
            for p in (pkg_candidates.get(d),)
            if p
        }
        if not shortlisted_pkg_candidates:
            return None

        highlight_version = not all_eq(
            chain((pkg.version,), (p['version'] for p in shortlisted_pkg_candidates.values()))
        )

        selection = select_one(
            pkg.name,
            [
                Choice(
                    [
                        ('', f'{d.as_uri()}=='),
                        ('class:attention' if highlight_version else '', v),
                    ],
                    d,
                    browser_url=u,
                    disabled=n,
                )
                for d, v, u, n in chain(
                    ((pkg.to_defn(), pkg.version, pkg.url, True),),
                    (
                        (d, p['version'], p['url'], False)
                        for d, p in shortlisted_pkg_candidates.items()
                    ),
                )
            ],
            can_skip=True,
        ).prompt()
        return selection if selection is not SKIP else None

    selections = {
        p.to_defn(): s
        for p, d in equivalent_pkg_defn_groups.items()
        for s in (select_alternative_pkg(p, d),)
        if s
    }

    if selections and confirm('Install selected add-ons?').prompt():
        Report(run_with_progress(pkg_management.replace(selections)).items()).generate_and_exit()


@cli.command
@click.argument('search-terms', nargs=-1, required=True, callback=_concat_search_terms_option)
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
    callback=_parse_iso_date_into_datetime_option,
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
def search(
    search_terms: str,
    limit: int,
    sources: Sequence[str],
    prefer_source: str | None,
    start_date: dt.datetime | None,
    no_exclude_installed: bool,
):
    "Search for add-ons to install."
    from ..catalogue.search import search
    from ._prompts import Choice, confirm, select_multiple

    catalogue_entries = run_with_progress(
        search(
            search_terms,
            limit=limit,
            sources=frozenset(sources),
            prefer_source=prefer_source,
            start_date=start_date,
            filter_installed='ident' if no_exclude_installed else 'exclude_from_all_sources',
        )
    )
    if catalogue_entries:
        choices = [
            Choice(f'{e.name}  ({d.as_uri()})', d, browser_url=e.url)
            for e in catalogue_entries
            for d in (definitions.Defn(e.source, e.slug or e.id, e.id),)
        ]
        selections = select_multiple('Select add-ons to install', choices=choices).prompt()
        if selections:
            if confirm('Install selected add-ons?').prompt():
                click.get_current_context().invoke(
                    install, addons=selections, replace_folders=False, dry_run=False
                )
        else:
            click.echo(
                'Nothing was selected; select add-ons with <space>'
                ' and confirm by pressing <enter>.'
            )

    else:
        click.echo('No results found.')


@cli.command('list')
@click.argument('addons', nargs=-1, callback=partial(_parse_uri_option, raise_invalid=False))
@click.option(
    '--format',
    '-f',
    'output_format',
    type=StrEnumChoiceParam(_ListFormat),
    default=_ListFormat.Simple,
    show_default=True,
    help='Change the output format.',
)
def list_installed(addons: Sequence[definitions.Defn], output_format: _ListFormat):
    "List installed add-ons."
    from ..pkg_db.models import Pkg, build_pkg_from_row_mapping

    with config_ctx.database() as connection:
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
            return map(build_pkg_from_row_mapping, repeat(connection), pkg_mappings)

        match output_format:
            case _ListFormat.Json:
                from cattrs.preconf.json import (
                    make_converter,  # pyright: ignore[reportUnknownVariableType]
                )

                click.echo(
                    make_converter().dumps(list(row_mappings_to_pkgs()), indent=2),
                )

            case _ListFormat.Detailed:
                import attrs

                def format_deps(pkg: Pkg):
                    return (
                        definitions.Defn(pkg.source, s or e.id).as_uri()
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
                    ''.join(
                        f'{definitions.Defn(p["source"], p["slug"]).as_uri()}\n'
                        for p in pkg_mappings
                    ),
                    nl=False,
                )


@cli.command(hidden=True)
@click.argument('addon', callback=partial(_parse_uri_option, raise_invalid=False))
def info(addon: definitions.Defn):
    "Alias of `list -f detailed`."
    click.get_current_context().invoke(
        list_installed, addons=(addon,), output_format=_ListFormat.Detailed
    )


@cli.command
@click.argument('addon', callback=partial(_parse_uri_option, raise_invalid=False))
def reveal(addon: definitions.Defn):
    "Bring an add-on up in your file manager."
    from .._utils.file import reveal_folder

    with config_ctx.database() as connection:
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
            reveal_folder(config_ctx.config().addon_dir / pkg_folder['name'])
        else:
            Report([(addon, _results.PkgNotInstalled())]).generate_and_exit()


@cli.command
@click.argument('addons', nargs=-1, callback=partial(_parse_uri_option, raise_invalid=False))
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
def view_changelog(addons: Sequence[definitions.Defn], convert: bool, remote: bool):
    """View installed and remote add-on changelogs.

    Invoked without arguments, it displays the changelogs of all add-ons
    to have been installed within one minute of the last add-on.

    By default, this command will only retrieve installed add-on changelogs.
    You can reverse this behaviour by passing `--remote`.  With `--remote`,
    you are also able to retrieve changelogs of older versions from sources
    which support the `version_eq` strategy, e.g. `github:foo/bar#version_eq=v1`.
    """

    from .._utils.aio import gather
    from ..definitions import ChangelogFormat

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
                match config_ctx.resolvers()[source].metadata.changelog_format:
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
        return f'{definitions.Defn(source, slug).as_uri()}:\n{body}'

    if remote:
        pkg_candidates, _ = pkg_management.bucketise_results(
            run_with_progress(pkg_management.resolve(addons)).items()
        )
        partial_pkgs: list[dict[str, Any]] = [
            {'source': d.source} | c for d, c in pkg_candidates.items()
        ]

    else:
        with config_ctx.database() as connection:
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
        gather(pkg_management.get_changelog(m['source'], m['changelog_url']) for m in partial_pkgs)
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


class _EditableConfigOptions(enum.StrEnum):
    AddonDir = 'addon_dir'
    GameFlavour = 'game_flavour'
    AutoUpdateCheck = 'global_config.auto_update_check'
    GithubAccessToken = 'global_config.access_tokens.github'
    CfcoreAccessToken = 'global_config.access_tokens.cfcore'
    WagoAddonsAccessToken = 'global_config.access_tokens.wago_addons'

    path: tuple[str, ...]

    def __new__(cls, value: str):
        self = str.__new__(cls, value)
        self._value_ = value
        self.path = tuple(value.split('.'))
        return self


@cli.command
@click.argument(
    'editable-config-values',
    nargs=-1,
    type=ManyOptionalChoiceValueParam(
        StrEnumChoiceParam(_EditableConfigOptions),
        value_types={
            _EditableConfigOptions.AutoUpdateCheck: click.BOOL,
        },
    ),
)
def configure(editable_config_values: Mapping[_EditableConfigOptions, Any]):
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

    import attrs

    from ..wow_installations import (
        ADDON_DIR_PARTS,
        Flavour,
        find_installations,
        infer_flavour_from_addon_dir,
    )
    from ._prompts import (
        SKIP,
        Choice,
        confirm,
        make_attrs_field_validator,
        password,
        path,
        select_one,
    )

    click_ctx = click.get_current_context().find_root()
    profile = click_ctx.params['profile']

    global_config = _config.GlobalConfig.read()

    config_values: dict[str, Any] | None = None
    try:
        config_values = attrs.asdict(_config.ProfileConfig.read(global_config, profile))
    except _config.UninitialisedConfigError:
        pass
    except Exception:
        _logging.logger.exception('unable to read existing config')

    is_new_profile = config_values is None
    if is_new_profile:
        config_values = {'profile': profile, 'global_config': attrs.asdict(global_config)}

    editable_config_values = dict(editable_config_values)
    if not editable_config_values:
        default_keys = {_EditableConfigOptions.AddonDir, _EditableConfigOptions.GameFlavour}
        if global_config.access_tokens.github is None:
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
            known_installations = list(global_config.iter_installations())
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
                validator=make_attrs_field_validator(
                    _config.ProfileConfig, 'addon_dir', _config.config_converter
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
                from .._github_auth import get_codes, poll_for_access_token
                from ..http import init_web_client

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


@cli.group('cache')
def _cache_group():
    "Manage the cache."


@_cache_group.command('clear')
def cache_clear():
    "Clear the instawow cache."
    import shutil

    shutil.rmtree(config_ctx.config().global_config.cache_dir)


@cli.group('debug')
def _debug_group():
    "Debug instawow."


@_debug_group.command('config')
def debug_config():
    "Print the active configuration."
    import json

    click.echo(json.dumps(config_ctx.config().unstructure_for_display(), indent=2))


@_debug_group.command('sources')
def debug_sources():
    "Print active source metadata."
    from cattrs.preconf.json import make_converter  # pyright: ignore[reportUnknownVariableType]

    json_converter = make_converter()

    click.echo(
        json_converter.dumps([r.metadata for r in config_ctx.resolvers().values()], indent=2)
    )


@_register_plugin_commands
@cli.group('plugins')
def _plugin_group():  # pyright: ignore[reportUnusedFunction]
    "Registered plug-ins."


@cli.command(hidden=True)
@click.option(
    '--start-date',
    callback=_parse_iso_date_into_datetime_option,
    help='Omit results before this date.',
    metavar='YYYY-MM-DD',
)
def generate_catalogue(start_date: dt.datetime | None):
    "Generate the master catalogue."
    import asyncio
    import json
    from pathlib import Path

    from ..catalogue.cataloguer import Catalogue

    catalogue = asyncio.run(Catalogue.collate(start_date))
    catalogue_json_dict = catalogue.to_json_dict()
    catalogue_path = Path(f'base-catalogue-v{catalogue.version}.json').resolve()
    catalogue_path.write_text(
        json.dumps(catalogue_json_dict, indent=2),
        encoding='utf-8',
    )
    catalogue_path.with_suffix(f'.compact{catalogue_path.suffix}').write_text(
        json.dumps(catalogue_json_dict, separators=(',', ':')),
        encoding='utf-8',
    )


main = partial(contextvars.copy_context().run, cli)
