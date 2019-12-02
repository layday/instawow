from __future__ import annotations

from enum import Enum
from functools import partial, wraps
from itertools import chain, islice
from operator import itemgetter
from pathlib import Path
from typing import (TYPE_CHECKING, cast,
                    Any, Callable, Generator, Iterable, List, Optional, Sequence, Tuple, Union)

import click

from . import exceptions as E
from . import models
from .resolvers import Strategies, Defn
from .utils import TocReader, bucketise, cached_property, is_outdated, setup_logging, tabulate, get_version

if TYPE_CHECKING:
    from .manager import CliManager


class Symbols(str, Enum):

    SUCCESS = click.style('✓', fg='green')
    FAILURE = click.style('✗', fg='red')
    WARNING = click.style('!', fg='blue')

    @classmethod
    def from_result(cls, result: E.ManagerResult) -> Symbols:
        if isinstance(result, E.InternalError):
            return cls.WARNING
        elif isinstance(result, E.ManagerError):
            return cls.FAILURE
        return cls.SUCCESS

    def __str__(self) -> str:
        return self.value


class Report:

    def __init__(self, results: Sequence[Tuple[Defn, E.ManagerResult]],
                 filter_fn: Callable = (lambda _: True)) -> None:
        self.results = results
        self.filter_fn = filter_fn

    @property
    def code(self) -> int:
        return any(r for _, r in self.results
                   if (isinstance(r, (E.ManagerError, E.InternalError))
                       and self.filter_fn(r)))

    def __str__(self) -> str:
        return '\n'.join(
            (f'{Symbols.from_result(r)} {click.style(str(a), bold=True)}\n'
             f'  {r.message}')
            for a, r in self.results
            if self.filter_fn(r))

    def generate(self) -> None:
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
    writer.writerows((Defn(p.origin, p.slug), p.options.strategy) for p in pkgs)
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


def _show_version(ctx: click.Context, _, value: bool) -> None:
    if not value:
        return

    __version__ = get_version()
    click.echo(f'instawow, {__version__}')
    ctx.exit()


class _InstallCommand(click.Command):

    def format_epilog(self, ctx, formatter):
        with formatter.section('Strategies'):
            formatter.write_dl((s.name, s.value) for s in islice(Strategies, 1, None))


class _AlwaysIterFile(click.File):

    def __call__(self, value, param=None, ctx=None):
        return self.convert(value, param, ctx) if value else ()


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
            def manager(self) -> CliManager:
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
                if is_outdated(manager):
                    click.echo(f'{Symbols.WARNING} instawow is out of date')
                return manager

            m = manager

        ctx.obj = ManagerSingleton


@main.command(cls=_InstallCommand)
@click.option('--replace', '-o',
              is_flag=True, default=False,
              help='Replace existing add-ons.')
@click.option('--with-strategy', '-s', 'strategic_addons',
              multiple=True,
              type=(click.Choice([s.name for s in Strategies]), str),
              callback=_callbackify(parse_into_defn_with_strategy),
              metavar='<STRATEGY ADDON>...',
              help='A strategy followed by an add-on definition.  '
                   'Use this if you want to install an add-on with a '
                   'strategy other than the default one.  '
                   'Repeatable.')
@click.option('--import', '-i', 'imported_addons',
              type=_AlwaysIterFile(encoding='utf-8'),
              callback=_callbackify(import_from_csv),
              help='Install add-ons from CSV.')
@click.argument('addons',
                nargs=-1, callback=_callbackify(parse_into_defn))
@_pass_manager
def install(manager, replace: bool,
            addons: Sequence[Defn], strategic_addons: Sequence[Defn],
            imported_addons: Sequence[Defn]) -> None:
    "Install add-ons."
    if not any((addons, strategic_addons, imported_addons)):
        raise click.UsageError('No add-ons given.')

    all_addons = chain(imported_addons, strategic_addons, addons)
    defn_buckets = bucketise(all_addons, key=itemgetter(0, 1))
    deduped_defns = [v for v, *_ in defn_buckets.values()]
    results = manager.install(deduped_defns, replace)
    Report(results.items()).generate_and_exit()


@main.command()
@click.argument('addons',
                nargs=-1, callback=_callbackify(parse_into_defn))
@_pass_manager
def update(manager, addons: Sequence[Defn]) -> None:
    "Update installed add-ons."
    if addons:
        values = addons
    else:
        values = [Defn(p.origin, p.slug) for p in manager.db_session.query(models.Pkg).all()]
    results = manager.update(values)
    # Hide package from output if up to date and ``update`` was invoked without args
    filter_fn = lambda r: addons or not isinstance(r, E.PkgUpToDate)
    Report(results.items(), filter_fn).generate_and_exit()


@main.command()
@click.argument('addons',
                nargs=-1, required=True, callback=_callbackify(parse_into_defn))
@_pass_manager
def remove(manager, addons: Sequence[Defn]) -> None:
    "Uninstall add-ons."
    results = manager.remove(addons)
    Report(results.items()).generate_and_exit()


@main.command()
@click.option('--auto', '-a',
              is_flag=True, default=False,
              help='Do not ask for user confirmation.')
@_pass_manager
def reconcile(manager, auto: bool) -> None:
    "Reconcile add-ons."
    from .matchers import _Addon, match_toc_ids, match_dir_names, get_leftovers
    from .models import is_pkg
    from .prompts import Choice, confirm, select, skip

    def _prompt(addons: Sequence[_Addon], pkgs: Sequence[models.Pkg]) -> Union[Tuple[()], Defn]:
        def create_choice(pkg):
            defn = Defn(pkg.origin, pkg.slug)
            title = [('', str(defn)),
                     ('', '=='),
                     ('class:hilite' if highlight_version else '', pkg.version),]
            return Choice(title, defn, pkg=pkg)

        # Highlight version if there's multiple of them
        highlight_version = len(bucketise(i.version for i in chain(addons, pkgs))) > 1
        choices = list(chain(map(create_choice, pkgs), (skip,)))
        addon = addons[0]
        # Use 'unsafe_ask' to let ^C bubble up
        selection = select(f'{addon.name} [{addon.version or "?"}]', choices).unsafe_ask()
        return selection

    def prompt(groups: Iterable[Tuple[Sequence[_Addon], Sequence[Any]]]) -> Generator[Defn, None, None]:
        for addons, results in groups:
            shortlist = list(filter(is_pkg, results))
            if shortlist:
                if auto:
                    pkg = shortlist[0]
                    yield Defn(pkg.origin, pkg.slug)
                    continue

                selection = _prompt(addons, shortlist)
                selection and (yield selection)

    def match_all():
        # Match in order of increasing heuristicitivenessitude
        for fn in (match_toc_ids,
                   match_dir_names,):
            leftovers = get_leftovers(manager)
            groups = manager.run(fn(manager, leftovers))
            yield list(prompt(groups))

    if not get_leftovers(manager):
        click.echo('No add-ons left to reconcile.')
        return

    if auto:
        for matches in match_all():
            results = manager.install(matches, replace=True)
            Report(results.items()).generate()
        return

    click.echo('''\
- Use the arrow keys to navigate, <o> to open an
  add-on in your browser and enter to make a selection.
- Versions that differ from the installed version
  or differ between choices are highlighted in purple.
- instawow will do a first pass of all of your add-ons
  looking for source IDs in TOC files, e.g. X-Curse-Project-ID.
- If it is unable to reconcile all of your add-ons
  it will perform a second pass to match add-on folders
  against the CurseForge and WoWInterface catalogues.
- Selected add-ons will be reinstalled.\
''')
    for selections in match_all():
        if selections and confirm('Install selected add-ons?').unsafe_ask():
            results = manager.install(selections, replace=True)
            Report(results.items()).generate()
    click.echo('- Unreconciled add-ons can be listed with '
               '`instawow list-folders -e`.')


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
                with formatter.section(Defn(pkg.origin, pkg.slug)):
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
            click.echo('\n'.join(str(Defn(p.origin, p.slug)) for p in pkgs))


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
    folders = {f for f in manager.config.addon_dir.iterdir() if f.is_dir()}
    if exclude_own:
        folders -= {manager.config.addon_dir / f.name
                    for f in manager.db_session.query(models.PkgFolder).all()}

    folder_tocs = ((n, n / f'{n.name}.toc') for n in folders)
    folder_readers = sorted((n, TocReader.from_path(t)) for n, t in folder_tocs if t.exists())
    if folder_readers:
        rows = [('folder', *(f'[{e}]' for e in toc_entries)),
                *((n.name, *(t[e].value for e in toc_entries)) for n, t in folder_readers)]
        click.echo(tabulate(rows))


@main.command(hidden=True)
@click.argument('addon', callback=_callbackify(partial(parse_into_defn, raise_invalid=False)))
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
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()


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
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()


@main.command()
def write_config() -> None:
    "Configure instawow."
    import os.path
    from prompt_toolkit.completion import PathCompleter, WordCompleter
    from prompt_toolkit.shortcuts import CompleteStyle, prompt
    from prompt_toolkit.validation import Validator
    from .config import Config

    prompt_ = partial(prompt, complete_style=CompleteStyle.READLINE_LIKE)

    class DirectoryCompleter(PathCompleter):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, expanduser=True, only_directories=True, **kwargs)

        def get_completions(self, document, complete_event):
            for completion in super().get_completions(document, complete_event):
                # Append slash to completions so we don't have to insert a '/' after every <tab>
                completion.text += '/'
                yield completion

    def validate_addon_dir(value: str) -> bool:
        path = os.path.expanduser(value)
        return os.path.isdir(path) and os.access(path, os.W_OK)

    ad_completer = DirectoryCompleter()
    ad_validator = Validator.from_callable(validate_addon_dir,
                                           error_message='must be a writable directory')
    addon_dir = prompt_('Add-on directory: ',
                        completer=ad_completer, validator=ad_validator)

    game_flavours = ('retail', 'classic')
    folders_to_flavours = [('_classic_', 'classic'),
                           ('_retail_', 'retail'), ('_ptr_', 'retail')]
    gf_completer = WordCompleter(game_flavours)
    gf_validator = Validator.from_callable(
        game_flavours.__contains__,
        error_message=f'must be one of: {", ".join(game_flavours)}')
    # Crude but the user's able to change the selection
    gf_default = next((f for s, f in folders_to_flavours if s in addon_dir), '')
    game_flavour = prompt_('Game flavour: ', default=gf_default,
                           completer=gf_completer, validator=gf_validator)

    config = Config(addon_dir=addon_dir, game_flavour=game_flavour).write()
    click.echo(f'Configuration written to: {config.config_file}')


@main.command()
@_pass_manager
def show_config(manager) -> None:
    "Show the active configuration."
    click.echo(manager.config.json(exclude=set()))


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
