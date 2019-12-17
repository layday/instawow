from __future__ import annotations

from functools import partial, wraps
from itertools import chain, islice
from pathlib import Path
from typing import (TYPE_CHECKING, Callable, Dict, Iterable, List, Optional, Sequence, Tuple,
                    Union, cast)

import click

from . import exceptions as E, models
from .resolvers import Defn, Strategies
from .utils import (TocReader, bucketise, cached_property, get_version, is_outdated, setup_logging,
                    tabulate)

if TYPE_CHECKING:
    from .manager import CliManager


class Report:
    _success = click.style('✓', fg='green')
    _failure = click.style('✗', fg='red')
    _warning = click.style('!', fg='blue')

    def __init__(self, results: Dict[Defn, E.ManagerResult],
                 filter_fn: Callable = (lambda _: True),
                 report_outdated: bool = True) -> None:
        self.results = results
        self.filter_fn = filter_fn
        self.report_outdated = report_outdated

    @property
    def code(self) -> int:
        return any(r for r in self.results.values()
                   if (isinstance(r, (E.ManagerError, E.InternalError))
                       and self.filter_fn(r)))

    def __str__(self) -> str:
        def _adorn_result(result: E.ManagerResult) -> str:
            if isinstance(result, E.InternalError):
                return self._warning
            elif isinstance(result, E.ManagerError):
                return self._failure
            return self._success

        return '\n'.join((f'{_adorn_result(r)} {click.style(str(a), bold=True)}\n'
                          f'  {r.message}')
                         for a, r in self.results.items()
                         if self.filter_fn(r))

    def generate(self) -> None:
        if self.report_outdated:
            manager = click.get_current_context().obj.m
            if is_outdated(manager):
                click.echo(f'{self._warning} instawow is out of date')

        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self) -> None:
        self.generate()
        ctx = click.get_current_context()
        ctx.exit(self.code)


def parse_into_defn(manager, value: Union[str, Sequence[str]], *,
                    raise_invalid: bool = True) -> Union[Defn, List[Defn]]:
    if isinstance(value, (list, tuple)):
        # Bucketise to remove dupes
        return list(bucketise(parse_into_defn(manager, v, raise_invalid=raise_invalid)
                              for v in value))

    value = cast(str, value)
    if ':' not in value:
        if raise_invalid:
            raise click.BadParameter(value)

        parts = ('*', value)
    else:
        for resolver in manager.resolvers.values():
            parts = resolver.decompose_url(value)
            if parts:
                break
        else:
            parts = value.partition(':')[::2]
    return Defn(*parts)


def parse_into_defn_with_strategy(manager, value: List[Tuple[str, str]]) -> List[Defn]:
    defns = parse_into_defn(manager, [d for _, d in value])
    strategies = (Strategies[s] for s, _ in value)
    return list(map(Defn.with_strategy, defns, strategies))


def export_to_csv(pkgs: List[models.Pkg]) -> str:
    "Export packages to CSV."
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(('defn', 'strategy'))
    writer.writerows((p.to_defn(), p.options.strategy) for p in pkgs)
    return buffer.getvalue()


def import_from_csv(manager, value: Iterable[str]) -> List[Defn]:
    "Import definitions from CSV."
    import csv

    rows = [(b, a) for a, b in islice(csv.reader(value), 1, None)]
    return parse_into_defn_with_strategy(manager, rows)


def _pass_manager(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        ctx = click.get_current_context()
        return fn(ctx.obj.m, *args, **kwargs)

    return wrapper


def _callbackify(fn: Callable) -> Callable:
    return lambda c, p, v: fn(c.obj.m, v)


def _combine_addons(fn: Callable) -> Callable:
    def combine(ctx, param, value):
        addons = ctx.params.setdefault('addons', [])
        if value:
            addons.extend(fn(ctx.obj.m, value))

    return combine


def _show_version(ctx: click.Context, param, value: bool) -> None:
    if value:
        __version__ = get_version()
        click.echo(f'instawow, version {__version__}')
        ctx.exit()


class _InstallCommand(click.Command):
    def format_epilog(self, ctx, formatter):
        with formatter.section('Strategies'):
            formatter.write_dl((s.name, s.value) for s in islice(Strategies, 1, None))


@click.group(context_settings={'help_option_names': ('-h', '--help')})
@click.option('--version',
              is_flag=True, default=False,
              expose_value=False, is_eager=True,
              callback=_show_version,
              help='Show the version and exit.')
@click.option('--debug',
              is_flag=True, default=False,
              help='Log more things.')
@click.pass_context
def main(ctx, debug: bool) -> None:
    "Add-on manager for World of Warcraft."
    if not ctx.obj:
        @object.__new__
        class ManagerSingleton:
            @cached_property
            def m(self) -> CliManager:
                from .config import Config
                from .manager import CliManager, prepare_db_session

                while True:
                    try:
                        config = Config.read().ensure_dirs()
                    except FileNotFoundError:
                        ctx.invoke(write_config)
                    else:
                        break

                setup_logging(config.logger_dir, 'DEBUG' if debug else 'INFO')
                db_session = prepare_db_session(config)
                manager = CliManager(config, db_session)
                return manager

        ctx.obj = ManagerSingleton


@main.command(cls=_InstallCommand)
@click.option('--replace', '-o',
              is_flag=True, default=False,
              help='Replace existing add-ons.')
@click.option('--import', '-i',
              type=click.File(encoding='utf-8'),
              callback=_combine_addons(import_from_csv),
              expose_value=False,
              help='Install add-ons from CSV.')
@click.option('--with-strategy', '-s',
              multiple=True,
              type=(click.Choice([s.name for s in Strategies]), str),
              callback=_combine_addons(parse_into_defn_with_strategy),
              expose_value=False,
              metavar='<STRATEGY ADDON>...',
              help='A strategy followed by an add-on definition.  '
                   'Use this if you want to install an add-on with a '
                   'strategy other than the default one.  '
                   'Repeatable.')
@click.argument('addons',
                nargs=-1, callback=_combine_addons(parse_into_defn),
                expose_value=False)
@_pass_manager
def install(manager, addons: Sequence[Defn], replace: bool) -> None:
    "Install add-ons."
    if not addons:
        raise click.UsageError('Require at least one of "ADDONS", '
                               '"--with-strategy" or "--import".')

    deduped_defns = [v for v, *_ in
                     bucketise(addons, lambda d: (d.source, d.name)).values()]
    results = manager.install(deduped_defns, replace)
    Report(results).generate_and_exit()


@main.command()
@click.argument('addons',
                nargs=-1, callback=_callbackify(parse_into_defn))
@_pass_manager
def update(manager, addons: Sequence[Defn]) -> None:
    "Update installed add-ons."
    def report_filter(result):
        # Hide package from output if up to date and ``update`` was invoked without args
        return addons or not isinstance(result, E.PkgUpToDate)

    defns = addons
    if not defns:
        defns = [p.to_defn() for p in manager.db_session.query(models.Pkg).all()]

    results = manager.update(defns)
    Report(results, report_filter).generate_and_exit()


@main.command()
@click.argument('addons',
                nargs=-1, required=True, callback=_callbackify(parse_into_defn))
@_pass_manager
def remove(manager, addons: Sequence[Defn]) -> None:
    "Uninstall add-ons."
    results = manager.remove(addons)
    Report(results).generate_and_exit()


@main.command()
@click.option('--auto', '-a',
              is_flag=True, default=False,
              help='Do not ask for user confirmation.')
@click.pass_context
def reconcile(ctx, auto: bool) -> None:
    "Reconcile add-ons."
    from .matchers import match_toc_ids, match_dir_names, get_folders
    from .models import Pkg, is_pkg
    from .prompts import PkgChoice, confirm, select, skip

    preamble = '''\
Use the arrow keys to navigate, <o> to open an add-on in your browser,
enter to make a selection and <s> to skip to the next item.

Versions that differ from the installed version or differ between choices
are highlighted in purple.

The reconciler will do a first pass of all of your add-ons looking for
source IDs in TOC files.  If it is unable to reconcile all of your add-ons
it will perform a second pass to match add-on folders against the CurseForge
and WoWInterface catalogues.

Selected add-ons _will_ be reinstalled.
'''

    manager = ctx.obj.m

    def prompt_one(addons, pkgs):
        def create_choice(pkg):
            defn = pkg.to_defn()
            title = [('', str(defn)),
                     ('', '=='),
                     ('class:highlight-sub' if highlight_version else '', pkg.version),]
            return PkgChoice(title, defn, pkg=pkg)

        # Highlight version if there's multiple of them
        highlight_version = len({i.version for i in chain(addons, pkgs)}) > 1
        choices = list(chain(map(create_choice, pkgs), (skip,)))
        addon = addons[0]
        # Using 'unsafe_ask' to let ^C bubble up
        selection = select(f'{addon.name} [{addon.version or "?"}]', choices).unsafe_ask()
        return selection

    def prompt(groups):
        for addons, results in groups:
            shortlist = list(filter(is_pkg, results))
            if shortlist:
                selection: Union[Defn, Tuple[()]]
                if auto:
                    pkg = shortlist[0]      # TODO: something more sophisticated
                    selection = pkg.to_defn()
                else:
                    selection = prompt_one(addons, shortlist)
                selection and (yield selection)

    def match_all():
        # Match in order of increasing heuristicitivenessitude
        for fn in (match_toc_ids,
                   match_dir_names,):
            groups = manager.run(fn(manager, (yield)))
            yield list(prompt(groups))
            leftovers = get_folders(manager)

    leftovers = get_folders(manager)
    if not leftovers:
        click.echo('No add-ons left to reconcile.')
        return
    if not auto:
        click.echo(preamble)

    matcher = match_all()
    for _ in matcher:
        selections = matcher.send(leftovers)
        if selections and (auto or confirm('Install selected add-ons?').unsafe_ask()):
            results = manager.install(selections, replace=True)
            Report(results).generate()

        leftovers = get_folders(manager)

    if not auto and leftovers:
        click.echo()
        ctx.invoke(list_folders, exclude_own=True)


@main.command()
@click.option('--limit', '-l',
              default=5, type=click.IntRange(1, 20, clamp=True),
              help='A number to limit results to.')
@click.argument('search-terms',
                nargs=-1, required=True, callback=lambda _, __, v: ' '.join(v))
@click.pass_context
def search(ctx, limit: int, search_terms: str) -> None:
    "Search for add-ons to install."
    from .prompts import Choice, checkbox, confirm

    manager = ctx.obj.m

    pkgs = manager.run(manager.search(search_terms, limit))
    if pkgs:
        choices = [Choice(f'{p.name}  ({d}=={p.version})', d, pkg=p)
                   for d, p in pkgs.items()]
        selections = checkbox('Select add-ons to install', choices=choices).unsafe_ask()
        if selections and confirm('Install selected add-ons?').unsafe_ask():
            ctx.invoke(install, addons=selections)


@main.command('list')
@click.option('--export', '-e',
              default=None, type=click.Path(dir_okay=False),
              help='Export listed add-ons to CSV.')
@click.option('--format', '-f', 'output_format',
              type=click.Choice(('simple', 'detailed', 'json')),
              default='simple', show_default=True,
              help='Change the output format.')
@click.argument('addons',
                nargs=-1,
                callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@_pass_manager
def list_installed(manager, addons: Sequence[Defn], export: Optional[str], output_format: str) -> None:
    "List installed add-ons."
    from sqlalchemy import and_, or_

    def format_deps(pkg):
        deps = (Defn(pkg.origin, d.id) for d in pkg.deps)
        deps = (d.with_name(getattr(manager.get(d), 'slug', d.name)) for d in deps)
        return map(str, deps)

    def get_desc_from_toc(folders):
        toc_reader = TocReader.from_path_name(manager.config.addon_dir / pkg.folders[0].name)
        return toc_reader['Notes'].value

    pkgs = (manager.db_session.query(models.Pkg)
            .filter(or_(models.Pkg.slug.contains(d.name) if d.source == '*' else
                        and_(models.Pkg.origin == d.source,
                             or_(models.Pkg.id == d.name, models.Pkg.slug == d.name))
                        for d in addons))
            .order_by(models.Pkg.origin, models.Pkg.name)
            .all())
    if export:
        Path(export).write_text(export_to_csv(pkgs), encoding='utf-8')
    elif pkgs:
        if output_format == 'json':
            from .models import MultiPkgModel

            click.echo(MultiPkgModel.from_orm(pkgs).json(indent=2))
        elif output_format == 'detailed':
            formatter = click.HelpFormatter(max_width=99)

            for pkg in pkgs:
                with formatter.section(pkg.to_defn()):
                    formatter.write_dl((
                        ('Name', pkg.name),
                        ('Description', get_desc_from_toc(pkg) if pkg.origin == 'wowi' else pkg.description),
                        ('URL', pkg.url),
                        ('Version', pkg.version),
                        ('Date published', pkg.date_published.isoformat(' ', 'minutes')),
                        ('Folders', ', '.join(f.name for f in pkg.folders)),
                        ('Dependencies', ', '.join(format_deps(pkg)) or ''),
                        ('Options', f'{{"strategy": "{pkg.options.strategy}"}}'),))
            click.echo(formatter.getvalue(), nl=False)
        else:
            click.echo('\n'.join(str(p.to_defn()) for p in pkgs))


@main.command()
@click.option('--exclude-own', '-e',
              is_flag=True, default=False,
              help='Exclude folders managed by instawow.')
@click.option('--toc-entry', '-t', 'toc_entries',
              multiple=True,
              help='An entry to extract from the TOC.  Repeatable.')
@_pass_manager
def list_folders(manager, exclude_own: bool, toc_entries: Sequence[str]) -> None:
    "List add-on folders."
    from .matchers import get_folders

    folders = sorted(get_folders(manager, exclude_own=exclude_own))
    if folders:
        rows = [('unreconciled' if exclude_own else 'folder',
                 *(f'[{e}]' for e in toc_entries)),
                *((f.name,
                  *(f.toc_reader[e].value for e in toc_entries)) for f in folders)]
        click.echo(tabulate(rows))


@main.command(hidden=True)
@click.argument('addons', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@click.pass_context
def info(ctx, addon: Defn) -> None:
    "Alias for `list -f detailed`."
    ctx.invoke(list_installed, addons=(addon,), output_format='detailed')


@main.command()
@click.argument('addon', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@_pass_manager
def visit(manager, addon: Defn) -> None:
    "Open an add-on's homepage in your browser."
    pkg = manager.get_from_substr(addon)
    if pkg:
        import webbrowser
        webbrowser.open(pkg.url)
    else:
        Report({addon: E.PkgNotInstalled()}).generate_and_exit()


@main.command()
@click.argument('addon', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
@_pass_manager
def reveal(manager, addon: Defn) -> None:
    "Open an add-on folder in your file manager."
    pkg = manager.get_from_substr(addon)
    if pkg:
        import webbrowser
        webbrowser.open((manager.config.addon_dir / pkg.folders[0].name).as_uri())
    else:
        Report({addon: E.PkgNotInstalled()}).generate_and_exit()


@main.command()
def write_config() -> None:
    "Configure instawow."
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.shortcuts import prompt

    from .config import Config
    from .prompts import DirectoryCompleter, PydanticValidator

    addon_dir = prompt('Add-on directory: ',
                       completer=DirectoryCompleter(),
                       validator=PydanticValidator(Config, 'addon_dir'))
    game_flavour = prompt('Game flavour: ',
                          default='classic' if '_classic_' in addon_dir else 'retail',
                          completer=WordCompleter(('retail', 'classic')),
                          validator=PydanticValidator(Config, 'game_flavour'))
    config = Config(addon_dir=addon_dir, game_flavour=game_flavour).write()
    click.echo(f'Configuration written to: {config.config_file}')


@main.command()
@_pass_manager
def show_config(manager) -> None:
    "Show the active configuration."
    click.echo(manager.config.json(indent=2))


@main.group('weakauras-companion')
def _weakauras_group() -> None:
    "Manage your WeakAuras."


@_weakauras_group.command('build')
@click.option('--account', '-a',
              required=True,
              help='Your account name.  This is used to locate '
                   'the WeakAuras data file.')
@_pass_manager
def build_weakauras_companion(manager, account: str) -> None:
    "Build the WeakAuras Companion add-on."
    from .wa_updater import WaCompanionBuilder

    manager.run(WaCompanionBuilder(manager).build(account))


@_weakauras_group.command('list')
@click.option('--account', '-a',
              required=True,
              help='Your account name.  This is used to locate '
                   'the WeakAuras data file.')
@_pass_manager
def list_installed_wago_auras(manager, account: str) -> None:
    "List WeakAuras installed from Wago."
    from .wa_updater import WaCompanionBuilder

    aura_groups = WaCompanionBuilder(manager).extract_installed_auras(account)
    installed_auras = sorted((a.id, a.url, str(a.ignore_wago_update).lower())
                             for v in aura_groups.values()
                             for a in v
                             if not a.parent)
    click.echo(tabulate([('name', 'url', 'ignore updates'),
                         *installed_auras]))
