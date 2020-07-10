from __future__ import annotations

from functools import partial
from itertools import chain, islice
from pathlib import Path
from textwrap import dedent, fill
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    FrozenSet,
    Generator,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

import click

from . import exceptions as E, models
from .resolvers import Defn, Strategies
from .utils import (
    TocReader,
    cached_property,
    get_version,
    is_outdated,
    setup_logging,
    tabulate,
    uniq,
)

if TYPE_CHECKING:
    from .manager import CliManager

    _R = TypeVar('_R')


class Report:
    _success = click.style('✓', fg='green')
    _failure = click.style('✗', fg='red')
    _warning = click.style('!', fg='blue')

    def __init__(
        self,
        results: Iterable[Tuple[Defn, E.ManagerResult]],
        filter_fn: Callable[[E.ManagerResult], bool] = lambda _: True,
    ):
        self.results = list(results)
        self.filter_fn = filter_fn

    @property
    def code(self) -> int:
        return any(
            r
            for _, r in self.results
            if isinstance(r, (E.ManagerError, E.InternalError)) and self.filter_fn(r)
        )

    def __str__(self) -> str:
        def _adorn_result(result: E.ManagerResult) -> str:
            if isinstance(result, E.InternalError):
                return self._warning
            elif isinstance(result, E.ManagerError):
                return self._failure
            return self._success

        return '\n'.join(
            f'{_adorn_result(r)} {click.style(str(a), bold=True)}\n'
            + fill(r.message, initial_indent='  ', subsequent_indent='  ')
            for a, r in self.results
            if self.filter_fn(r)
        )

    def generate(self):
        manager: CliManager = click.get_current_context().obj.m
        if manager.config.auto_update_check and is_outdated(manager):
            click.echo(f'{self._warning} instawow is out of date')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self):
        self.generate()
        ctx = click.get_current_context()
        ctx.exit(self.code)


class ManagerWrapper:
    def __init__(self, debug: bool = False):
        self.debug = debug

    @cached_property
    def m(self) -> CliManager:
        import asyncio

        from .config import Config
        from .manager import CliManager, prepare_db_session

        # TODO: rm once https://github.com/aio-libs/aiohttp/issues/4324 is fixed
        policy = getattr(asyncio, 'WindowsSelectorEventLoopPolicy', None)
        if policy:
            asyncio.set_event_loop_policy(policy())

        while True:
            try:
                config = Config.read().ensure_dirs()
            except FileNotFoundError:
                ctx = click.get_current_context()
                ctx.invoke(configure)
            else:
                break

        setup_logging(config.logger_dir, 'DEBUG' if self.debug else 'INFO')
        db_session = prepare_db_session(config)
        manager = CliManager(config, db_session)
        return manager


M = ManagerWrapper


@overload
def parse_into_defn(manager: CliManager, value: str, *, raise_invalid: bool = True) -> Defn:
    ...


@overload
def parse_into_defn(
    manager: CliManager, value: Sequence[str], *, raise_invalid: bool = True
) -> List[Defn]:
    ...


def parse_into_defn(
    manager: CliManager, value: Sequence[str], *, raise_invalid: bool = True
) -> Union[Defn, List[Defn]]:
    if not isinstance(value, str):
        defns = (parse_into_defn(manager, v, raise_invalid=raise_invalid) for v in value)
        return uniq(defns)

    delim = ':'
    any_source = '*'
    if delim not in value:
        if raise_invalid:
            raise click.BadParameter(value)
        parts = (any_source, value)
    else:
        parts = manager.pair_url(value)
        if not parts:
            parts = value.partition(delim)[::2]
    return Defn(*parts)


def parse_into_defn_with_strategy(
    manager: CliManager, value: Sequence[Tuple[str, str]]
) -> List[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    strategies = (Strategies[s] for s, _ in value)
    return list(map(Defn.with_strategy, defns, strategies))


def parse_into_defn_with_version(
    manager: CliManager, value: Sequence[Tuple[str, str]]
) -> List[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    return list(map(Defn.with_version, defns, (v for v, _ in value)))


def export_to_csv(pkgs: Sequence[models.Pkg], path: Path):
    "Export packages to CSV."
    import csv

    with Path(path).open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(('defn', 'strategy'))
        writer.writerows((Defn.from_pkg(p), p.options.strategy) for p in pkgs)


def import_from_csv(manager: CliManager, path: Path) -> List[Defn]:
    "Import definitions from CSV."
    import csv

    with Path(path).open(encoding='utf-8', newline='') as contents:
        rows = [(b, a) for a, b in islice(csv.reader(contents), 1, None)]
    return parse_into_defn_with_strategy(manager, rows)


def _callbackify(fn: Callable[..., _R]) -> Callable[[click.Context, Any, Any], _R]:
    return lambda c, _, v: fn(c.obj.m, v)


def _combine_into(param_name: str, fn: Callable[..., Any]):
    def combine(ctx: click.Context, param: Any, value: Any):
        addons = ctx.params.setdefault(param_name, [])
        if value:
            addons.extend(fn(ctx.obj.m, value))

    return combine


def _show_version(ctx: click.Context, param: Any, value: bool):
    if value:
        __version__ = get_version()
        click.echo(f'instawow, version {__version__}')
        ctx.exit()


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.option(
    '--version',
    is_flag=True,
    default=False,
    callback=_show_version,
    expose_value=False,
    is_eager=True,
    help='Show the version and exit.',
)
@click.option('--debug', is_flag=True, default=False, help='Log more things.')
@click.pass_context
def main(ctx: click.Context, debug: bool):
    "Add-on manager for World of Warcraft."
    if not ctx.obj:
        ctx.obj = ManagerWrapper(debug)


@main.command()
@click.option('--replace', '-o', is_flag=True, default=False, help='Replace existing add-ons.')
@click.option(
    '--import',
    '-i',
    type=click.Path(dir_okay=False, exists=True),
    callback=_combine_into('addons', import_from_csv),
    expose_value=False,
    help='Install add-ons from CSV.',
)
@click.option(
    '--with-strategy',
    '-s',
    multiple=True,
    type=(click.Choice([s.name for s in Strategies.exposed()]), str),
    callback=_combine_into('addons', parse_into_defn_with_strategy),
    expose_value=False,
    metavar='<STRATEGY ADDON>...',
    help='A strategy followed by an add-on definition.  '
    'Available strategies are: '
    f'{", ".join(repr(s.name) for s in Strategies.exposed())}.',
)
@click.option(
    '--version',
    multiple=True,
    type=(str, str),
    callback=_combine_into('addons', parse_into_defn_with_version),
    expose_value=False,
    metavar='<VERSION ADDON>...',
    help='A version followed by an add-on definition.',
)
@click.argument(
    'addons', nargs=-1, callback=_combine_into('addons', parse_into_defn), expose_value=False
)
@click.pass_obj
def install(obj: M, addons: Sequence[Defn], replace: bool):
    "Install add-ons."
    if not addons:
        raise click.UsageError(
            'You must provide at least one of "ADDONS", "--with-strategy", '
            '"--version" or "--import"'
        )

    results = obj.m.run(obj.m.install(addons, replace))
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, callback=_callbackify(parse_into_defn))
@click.pass_obj
def update(obj: M, addons: Sequence[Defn]):
    "Update installed add-ons."

    def report_filter(result: E.ManagerResult):
        # Hide package from output if up to date and ``update`` was invoked without args
        return cast(bool, addons or not isinstance(result, E.PkgUpToDate))

    defns = addons
    if not defns:
        defns = [Defn.from_pkg(p) for p in obj.m.db_session.query(models.Pkg).all()]

    results = obj.m.run(obj.m.update(defns))
    Report(results.items(), report_filter).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=_callbackify(parse_into_defn))
@click.pass_obj
def remove(obj: M, addons: Sequence[Defn]):
    "Remove add-ons."
    results = obj.m.run(obj.m.remove(addons))
    Report(results.items()).generate_and_exit()


@main.command()
@click.option(
    '--undo',
    is_flag=True,
    default=False,
    help='Undo rollback by reinstalling an add-on using the default strategy.',
)
@click.argument('addon', callback=_callbackify(parse_into_defn))
@click.pass_context
def rollback(ctx: click.Context, addon: Defn, undo: bool):
    "Roll an add-on back to an older version."
    from .prompts import Choice, select

    manager = ctx.obj.m

    pkg = manager.get_pkg(addon)
    if not pkg:
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()
        return  # noop

    resolver = manager.resolvers[pkg.source]
    if not resolver.supports_rollback:
        Report(
            [(addon, E.PkgFileUnavailable('source does not support rollback'))]
        ).generate_and_exit()

    if undo:
        Report(
            chain(
                manager.run(manager.remove([addon])).items(),
                manager.run(manager.install([addon], replace=False)).items(),
            )
        ).generate_and_exit()

    versions = (
        manager.db_session.query(models.PkgVersionLog)
        .filter(
            models.PkgVersionLog.pkg_source == pkg.source, models.PkgVersionLog.pkg_id == pkg.id
        )
        .order_by(models.PkgVersionLog.install_time.desc())
        .limit(10)
        .all()
    )
    if len(versions) <= 1:
        Report([(addon, E.PkgFileUnavailable('cannot find older versions'))]).generate_and_exit()

    reconstructed_defn = Defn.from_pkg(pkg)
    choices = [Choice([('', v.version)], disabled=(v.version == pkg.version)) for v in versions]
    selection = select(
        f'Select version of {reconstructed_defn} for rollback', choices
    ).unsafe_ask()
    Report(
        chain(
            manager.run(manager.remove([reconstructed_defn])).items(),
            manager.run(
                manager.install([reconstructed_defn.with_version(selection)], replace=False)
            ).items(),
        )
    ).generate_and_exit()


@main.command()
@click.option(
    '--auto', '-a', is_flag=True, default=False, help='Do not ask for user confirmation.'
)
@click.option(
    '--list-unreconciled', is_flag=True, default=False, help='List unreconciled add-ons and exit.'
)
@click.pass_context
def reconcile(ctx: click.Context, auto: bool, list_unreconciled: bool):
    "Reconcile pre-installed add-ons."
    from .matchers import AddonFolder, get_folders, match_dir_names, match_toc_ids, match_toc_names
    from .models import is_pkg
    from .prompts import PkgChoice, confirm, select, skip

    preamble = dedent(
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

    manager = ctx.obj.m

    def prompt_one(addons: List[AddonFolder], pkgs: List[models.Pkg]) -> Union[Defn, Tuple[()]]:
        def create_choice(pkg: models.Pkg):
            defn = Defn.from_pkg(pkg)
            title = [
                ('', str(defn)),
                ('', '=='),
                ('class:highlight-sub' if highlight_version else '', pkg.version),
            ]
            return PkgChoice(title, defn, pkg=pkg)

        # Highlight version if there's multiple of them
        highlight_version = len({i.version for i in chain(addons, pkgs)}) > 1
        choices = list(chain(map(create_choice, pkgs), (skip,)))
        addon = addons[0]
        # Using 'unsafe_ask' to let ^C bubble up
        selection = select(f'{addon.name} [{addon.version or "?"}]', choices).unsafe_ask()
        return selection

    def prompt(groups: Iterable[Tuple[List[AddonFolder], List[Defn]]]) -> Iterable[Defn]:
        results = manager.run(manager.resolve(list({d for _, b in groups for d in b})))
        for addons, defns in groups:
            shortlist = list(filter(is_pkg, (results[d] for d in defns)))
            if shortlist:
                if auto:
                    pkg = shortlist[0]  # TODO: something more sophisticated
                    selection = Defn.from_pkg(pkg)
                else:
                    selection = prompt_one(addons, shortlist)
                selection and (yield selection)

    def match_all() -> Generator[List[Defn], FrozenSet[AddonFolder], None]:
        # Match in order of increasing heuristicitivenessitude
        for fn in (
            match_toc_ids,
            match_dir_names,
            match_toc_names,
        ):
            groups = manager.run(fn(manager, (yield [])))
            yield list(prompt(groups))

    leftovers = get_folders(manager)
    if list_unreconciled:
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))
        return
    elif not leftovers:
        click.echo('No add-ons left to reconcile.')
        return
    elif not auto:
        click.echo(preamble)

    matcher = match_all()
    for _ in matcher:  # Skip over consumer yields
        selections = matcher.send(leftovers)
        if selections and (auto or confirm('Install selected add-ons?').unsafe_ask()):
            results = manager.run(manager.install(selections, replace=True))
            Report(results.items()).generate()

        leftovers = get_folders(manager)

    if leftovers:
        click.echo()
        table_rows = [('unreconciled',), *((f.name,) for f in sorted(leftovers))]
        click.echo(tabulate(table_rows))


@main.command()
@click.option(
    '--limit',
    '-l',
    default=10,
    type=click.IntRange(1, 20, clamp=True),
    help='A number to limit results to.',
)
@click.argument(
    'search-terms', nargs=-1, required=True, callback=lambda _, __, v: ' '.join(v)
)  # type: ignore
@click.pass_context
def search(ctx: click.Context, limit: int, search_terms: str):
    "Search for add-ons to install."
    from .prompts import PkgChoice, checkbox, confirm

    manager = ctx.obj.m

    pkgs = manager.run(manager.search(search_terms, limit))
    if pkgs:
        choices = [PkgChoice(f'{p.name}  ({d}=={p.version})', d, pkg=p) for d, p in pkgs.items()]
        selections = checkbox('Select add-ons to install', choices=choices).unsafe_ask()
        if selections and confirm('Install selected add-ons?').unsafe_ask():
            ctx.invoke(install, addons=selections)


@main.command('list')
@click.option(
    '--export',
    '-e',
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help='Export listed add-ons to CSV.',
)
@click.option(
    '--format',
    '-f',
    'output_format',
    type=click.Choice(('simple', 'detailed', 'json')),
    default='simple',
    show_default=True,
    help='Change the output format.',
)
@click.argument(
    'addons', nargs=-1, callback=_callbackify(partial(parse_into_defn, raise_invalid=False))
)
@click.pass_obj
def list_(obj: M, addons: Sequence[Defn], export: Optional[str], output_format: str):
    "List installed add-ons."
    from sqlalchemy import and_, or_

    def format_deps(pkg: models.Pkg):
        deps = (Defn(pkg.source, d.id) for d in pkg.deps)
        deps = (d.with_name(getattr(obj.m.get_pkg(d), 'slug', d.name)) for d in deps)
        return map(str, deps)

    def get_desc(pkg: models.Pkg):
        if pkg.source == 'wowi':
            toc_reader = TocReader.from_path_name(obj.m.config.addon_dir / pkg.folders[0].name)
            return toc_reader['Notes'].value
        else:
            return pkg.description

    pkgs = (
        obj.m.db_session.query(models.Pkg)
        .filter(
            or_(
                *(
                    models.Pkg.slug.contains(d.name)
                    if d.source == '*'
                    else and_(
                        models.Pkg.source == d.source,
                        or_(models.Pkg.id == d.name, models.Pkg.slug == d.name),
                    )
                    for d in addons
                )
            )
        )
        .order_by(models.Pkg.source, models.Pkg.name)
        .all()
    )
    if export:
        export_to_csv(pkgs, cast(Path, export))
    elif pkgs:
        if output_format == 'json':
            from .models import MultiPkgModel

            click.echo(MultiPkgModel.from_orm(pkgs).json(indent=2))
        elif output_format == 'detailed':
            formatter = click.HelpFormatter(max_width=99)
            for pkg in pkgs:
                with formatter.section(str(Defn.from_pkg(pkg))):
                    formatter.write_dl(
                        (
                            ('Name', pkg.name),
                            ('Description', get_desc(pkg)),
                            ('URL', pkg.url),
                            ('Version', pkg.version),
                            ('Date published', pkg.date_published.isoformat(' ', 'minutes')),
                            ('Folders', ', '.join(f.name for f in pkg.folders)),
                            ('Dependencies', ', '.join(format_deps(pkg))),
                            ('Options', f'{{"strategy": "{pkg.options.strategy}"}}'),
                        )
                    )

            click.echo(formatter.getvalue(), nl=False)
        else:
            click.echo('\n'.join(str(Defn.from_pkg(p)) for p in pkgs))


@main.command(hidden=True)
@click.argument('addon', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@click.pass_context
def info(ctx: click.Context, addon: Defn):
    "Alias of `list -f detailed`."
    ctx.invoke(list_, addons=(addon,), output_format='detailed')


@main.command()
@click.argument('addon', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@click.pass_obj
def reveal(obj: M, addon: Defn):
    "Bring an add-on up in your file manager."
    pkg = obj.m.get_pkg_from_substr(addon)
    if pkg:
        import webbrowser

        webbrowser.open((obj.m.config.addon_dir / pkg.folders[0].name).as_uri())
    else:
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.option(
    '--active',
    'show_active',
    is_flag=True,
    default=False,
    help='Show the active configuration and exit.',
)
@click.pass_obj
def configure(obj: M, show_active: bool):
    "Configure instawow."
    if show_active:
        click.echo(obj.m.config.json(indent=2))
        return

    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.shortcuts import prompt

    from .config import Config
    from .prompts import DirectoryCompleter, PydanticValidator

    addon_dir = prompt(
        'Add-on directory: ',
        completer=DirectoryCompleter(),
        validator=PydanticValidator(Config, 'addon_dir'),
    )
    game_flavour = prompt(
        'Game flavour: ',
        default='classic' if '_classic_' in addon_dir else 'retail',
        completer=WordCompleter(['retail', 'classic']),
        validator=PydanticValidator(Config, 'game_flavour'),
    )
    config = Config(addon_dir=addon_dir, game_flavour=game_flavour).write()
    click.echo(f'Configuration written to: {config.config_file}')


@main.group('weakauras-companion')
def _weakauras_group():
    "Manage your WeakAuras."


@_weakauras_group.command('build')
@click.option(
    '--account',
    '-a',
    required=True,
    help='Your account name.  This is used to locate the WeakAuras data file.',
)
@click.pass_obj
def build_weakauras_companion(obj: M, account: str):
    "Build the WeakAuras Companion add-on."
    from .wa_updater import WaCompanionBuilder

    obj.m.run(WaCompanionBuilder(obj.m, account).build())


@_weakauras_group.command('list')
@click.option(
    '--account',
    '-a',
    required=True,
    help='Your account name.  This is used to locate the WeakAuras data file.',
)
@click.pass_obj
def list_installed_wago_auras(obj: M, account: str):
    "List WeakAuras installed from Wago."
    from .wa_updater import WaCompanionBuilder

    aura_groups = WaCompanionBuilder(obj.m, account).extract_installed_auras()
    installed_auras = sorted(
        (Path(g.Meta.filename).stem, a.id, a.url, 'yes' if a.ignore_wago_update else 'no')
        for g in aura_groups
        for v in g.entries.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('add-on', 'name', 'URL', 'ignore updates'), *installed_auras]))


@main.command(hidden=True)
@click.argument('filename', type=click.Path(dir_okay=False))
def generate_catalogue(filename: str):
    import asyncio

    from .resolvers import MasterCatalogue

    catalogue = asyncio.run(MasterCatalogue.collate())
    expanded = Path(filename)
    expanded.write_text(catalogue.json(indent=2), encoding='utf-8')

    compact = expanded.with_suffix(f'.compact{expanded.suffix}')
    compact.write_text(catalogue.json(separators=(',', ':')), encoding='utf-8')
