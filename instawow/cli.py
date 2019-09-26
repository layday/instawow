from __future__ import annotations

from enum import Enum
from functools import partial, update_wrapper
from textwrap import fill
from typing import TYPE_CHECKING
from typing import (Any, Callable, Generator, Iterable, List, NamedTuple,
                    Optional, Sequence, Set, Tuple, Union)

import click

from . import __version__
from .config import Config
from . import exceptions as E
from .manager import CliManager, prepare_db_session
from .models import Pkg, PkgFolder
from .resolvers import Defn, Strategies
from .utils import TocReader, bucketise, cached_property, is_outdated, setup_logging


class Symbols(str, Enum):

    SUCCESS = click.style('✓', fg='green')
    FAILURE = click.style('✗', fg='red')
    WARNING = click.style('!', fg='blue')

    @classmethod
    def from_result(cls, result: E.ManagerResult) -> Symbols:
        for type_, symbol in ((E.InternalError, cls.WARNING),
                              (E.ManagerError,  cls.FAILURE),
                              (E.ManagerResult, cls.SUCCESS)):
            if isinstance(result, type_):
                return symbol

    def __str__(self) -> str:
        return self.value


class Report:

    def __init__(self, results: Sequence[Tuple[str, E.ManagerResult]],
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
            if self.filter_fn(r)
            )

    def generate(self) -> None:
        report = str(self)
        if report:
            click.echo(report)

    def generate_and_exit(self) -> None:
        self.generate()
        ctx = click.get_current_context()
        ctx.exit(self.code)


def tabulate(rows: Iterable, *, show_index: bool = True) -> str:
    from texttable import Texttable, Texttable as c

    table = Texttable(max_width=0).set_deco(c.BORDER | c.HEADER | c.VLINES)
    if show_index:
        iter_rows = iter(rows)
        header = next(iter_rows)
        rows = [('', *header), *((i, *v) for i, v in enumerate(iter_rows, start=1))]
        table.set_cols_align(('r', *('l' for _ in header)))
    return table.add_rows(rows).draw()


def decompose_pkg_uri(ctx: click.Context,
                      param: Any,
                      value: Union[str, Tuple[str, ...]],
                      *,
                      raise_for_invalid_uri: bool = True) -> Any:
    if isinstance(value, (list, tuple)):
        return list(bucketise(decompose_pkg_uri(ctx, param, v) for v in value))

    if ':' not in value:
        if raise_for_invalid_uri:
            raise click.BadParameter(value)

        parts = ('*', value)
    else:
        for resolver in ctx.obj.m.resolvers.values():
            parts = resolver.decompose_url(value)
            if parts:
                break
        else:
            parts = value.partition(':')[::2]
    return Defn(*parts)


def get_pkg_from_substr(manager: CliManager, defn: Defn) -> Optional[Pkg]:
    pkg = manager.get(defn)
    pkg = pkg or (manager.db_session.query(Pkg).filter(Pkg.slug.contains(defn.name))
                  .order_by(Pkg.name).first())
    return pkg


class _OrigCmdOrderGroup(click.Group):

    def list_commands(self, ctx: click.Context) -> List[str]:
        # The default is ``sorted(self.commands)``
        return list(self.commands)


def _pass_manager(f: Callable) -> Callable:
    def new_func(*args: Any, **kwargs: Any) -> Callable:
        return f(click.get_current_context().obj.m, *args, **kwargs)
    return update_wrapper(new_func, f)


@click.group(cls=_OrigCmdOrderGroup,
             context_settings={'help_option_names': ['-h', '--help']})
@click.version_option(__version__, prog_name='instawow')
@click.option('--debug',
              is_flag=True, default=False, flag_value='DEBUG',
              help='Log more things.')
@click.pass_context
def main(ctx, debug):
    "Add-on manager for World of Warcraft."
    if not ctx.obj:
        @object.__new__
        class ManagerSingleton:
            @cached_property
            def manager(self) -> CliManager:
                while True:
                    try:
                        config = Config.read().write()
                    except FileNotFoundError:
                        ctx.invoke(write_config)
                    else:
                        break

                setup_logging(config, debug or 'INFO')
                db_session = prepare_db_session(config)
                manager = CliManager(config, db_session)
                if is_outdated(manager):
                    click.echo(f'{Symbols.WARNING} instawow is out of date')
                return manager

            m = manager

        ctx.obj = ManagerSingleton


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=decompose_pkg_uri)
@click.option('--strategy', '-s',
              type=click.Choice({s.value for s in Strategies}),
              default=Strategies.default.value,
              help="Whether to install the latest published version "
                   "('default') or the very latest upload ('latest').")
@click.option('--replace', '-o',
              is_flag=True, default=False,
              help='Replace existing add-ons.')
@_pass_manager
def install(manager, addons, strategy, replace) -> None:
    "Install add-ons."
    results = list(zip(addons, manager.install(addons, strategy, replace)))
    Report(results).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, callback=decompose_pkg_uri)
@_pass_manager
def update(manager, addons) -> None:
    "Update installed add-ons."
    if addons:
        values = addons
    else:
        values = [Defn(p.origin, p.slug) for p in manager.db_session.query(Pkg).all()]
    results = list(zip(values, manager.update(values)))
    # Hide package from output if up to date and ``update`` was invoked without args
    filter_fn = lambda r: addons or not isinstance(r, E.PkgUpToDate)
    Report(results, filter_fn).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=decompose_pkg_uri)
@_pass_manager
def remove(manager, addons) -> None:
    "Uninstall add-ons."
    results = list(zip(addons, manager.remove(addons)))
    Report(results).generate_and_exit()


@main.command()
@click.pass_context
def reconcile(ctx) -> None:
    "Reconcile add-ons."
    from asyncio import gather
    from functools import reduce
    from itertools import chain, repeat, starmap

    from prompt_toolkit.styles import Style
    from questionary import Choice as _Choice, confirm
    from questionary.question import Question

    class Choice(_Choice):
        def __init__(self, *args: Any, pkg: Optional[Pkg] = None, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.pkg = pkg

    class _Addon(NamedTuple):
        name: str
        reader: TocReader

        @property
        def version(self) -> str:
            return self.reader['Version', 'X-Packaged-Version'].value

    manager = ctx.obj.m
    resolve = partial(manager.resolve, strategy='default')
    install = partial(manager.install, strategy='default', replace=True)
    TocReader_ = lambda n: TocReader.from_path_name(manager.config.addon_dir / n)

    qstyle = Style([('qmark', 'fg:ansicyan'),
                    ('question', ''),
                    ('answer', 'fg: nobold'),
                    ('hilite', 'fg:ansimagenta'),
                    ('skipped', 'fg:ansiyellow')])
    confirm_ = partial(confirm, style=qstyle)
    skip = Choice([('', 'skip')], ())

    def select(message: str, choices: List[Choice]) -> Question:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
        from questionary.prompts.common import InquirerControl, create_inquirer_layout

        def get_prompt_tokens():
            tokens = [('class:qmark', '-'),
                      ('class:x-question', f' {message} ')]
            if ic.is_answered:
                answer = ''.join(t for _, t in ic.get_pointed_at().title)
                tokens += [('', '  '),
                           ('class:skipped' if answer == 'skip' else '', answer)]
            return tokens

        ic = InquirerControl(choices, None,
                             use_indicator=False, use_shortcuts=False, use_pointer=True)
        bindings = KeyBindings()

        @bindings.add(Keys.ControlQ, eager=True)
        @bindings.add(Keys.ControlC, eager=True)
        def _(event):
            event.app.exit(exception=KeyboardInterrupt, style='class:aborting')

        @bindings.add(Keys.Down, eager=True)
        @bindings.add('j', eager=True)
        def move_cursor_down(event):
            ic.select_next()
            while not ic.is_selection_valid():
                ic.select_next()

        @bindings.add(Keys.Up, eager=True)
        @bindings.add('k', eager=True)
        def move_cursor_up(event):
            ic.select_previous()
            while not ic.is_selection_valid():
                ic.select_previous()

        @bindings.add(Keys.ControlM, eager=True)
        def set_answer(event):
            ic.is_answered = True
            event.app.exit(result=ic.get_pointed_at().value)

        @bindings.add('o', eager=True)
        def open_url(event):
            pkg = ic.get_pointed_at().pkg
            if pkg:
                import webbrowser
                webbrowser.open(pkg.url)

        @bindings.add(Keys.Any)
        def other(event):
            # Disallow inserting other text
            pass

        layout = create_inquirer_layout(ic, get_prompt_tokens)
        app = Application(layout=layout, key_bindings=bindings, style=qstyle)
        return Question(app)

    def _prompt(addons: Sequence[_Addon], pkgs: Sequence[Pkg]) -> Tuple[Sequence[_Addon], Defn]:
        def create_choice(pkg):
            defn = Defn(pkg.origin, pkg.slug)
            title = [('', str(defn)),
                     ('', '=='),
                     ('class:hilite' if highlight_version else '', pkg.version),]
            return Choice(title, (addons, defn), pkg=pkg)

        # Highlight version if there's multiple of them
        highlight_version = len(bucketise(i.version for i in chain(addons, pkgs))) > 1
        choices = list(chain(map(create_choice, pkgs), (skip,)))
        addon = addons[0]
        # Use 'unsafe_ask' to let ^C bubble up
        selection = select(f'{addon.name} [{addon.version or "?"}]', choices).unsafe_ask()
        return selection

    def prompt(groups: Iterable[Tuple[Sequence[_Addon], Sequence[Pkg]]]) -> Generator[Tuple[Sequence[_Addon], Defn], None, None]:
        for addons, results in groups:
            shortlist = [r for r in results if isinstance(r, Pkg)]
            if shortlist:
                selection = _prompt(addons, shortlist)
                selection and (yield selection)

    def match_toc_ids_from_sources(leftovers: Set[str]) -> Iterable[Tuple[List[_Addon], Any]]:
        "Attempt to match add-ons from host IDs contained in TOC files."
        ids_to_sources = {'X-WoWI-ID': 'wowi',
                          'X-Tukui-ProjectID': 'tukui',
                          'X-Curse-Project-ID': 'curse',}

        def merge_ids_and_dirs(buckets, match):
            dirs, ids = match
            for index, (old_dirs, old_ids) in enumerate(buckets):
                if ids & old_ids:
                    buckets[index] = (old_dirs + dirs, old_ids | ids)
                    break
            else:
                buckets.append(match)
            return buckets

        dir_tocs = ((n, TocReader_(n)) for n in sorted(leftovers))
        maybe_ids = (((n, r), (r[i] for i in ids_to_sources)) for n, r in dir_tocs)
        buckets = reduce(merge_ids_and_dirs,
                         (([t], {Defn(ids_to_sources[v.key], v.value) for v in i if v})
                          for t, i in maybe_ids),
                         [])
        results = manager.run(resolve(set(chain.from_iterable(i for _, i in buckets))))
        groups = ((list(starmap(_Addon, k)), list(map(results.__getitem__, v)))
                  for k, v in buckets)
        return groups

    def match_dir_names(leftovers: Set[str]) -> Iterable[Tuple[List[_Addon], Any]]:
        "Attempt to match folders against the WoWInterface catalogue."
        async def fetch_catalogues(*urls):
            async def fetch(url):
                async with manager.web_client.get(url) as response:
                    # The CurseForge catalogue has a content type of 'text/plain' -
                    # aiohttp's default behaviour is to raise when it's not application/json
                    return await response.json(content_type=None)

            return await gather(*map(fetch, urls))

        def merge_dirs_and_ids(buckets, match):
            dirs, id_ = match
            for index, (old_dirs, old_ids) in enumerate(buckets):
                if old_dirs & dirs:
                    buckets[index] = (old_dirs | dirs, old_ids | {id_})
                    break
            else:
                buckets.append((dirs, {id_}))
            return buckets

        urls = (manager.resolvers['curse'].folders_url,
                manager.resolvers['wowi'].list_api_url,)
        curse_catalogue, wowi_catalogue = manager.run(fetch_catalogues(*urls))
        dirs = chain(((set(e['UIDir']), Defn('wowi', e['UID']))
                      for e in wowi_catalogue),
                     ((set(i[2]), Defn('curse', str(i[0])))
                      for i in curse_catalogue
                      if manager.config.game_flavour in i[1]))
        buckets = reduce(merge_dirs_and_ids,
                         ((d & leftovers, u) for d, u in dirs if d & leftovers),
                         [])
        results = manager.run(resolve(list({u for _, i in buckets for u in i})))
        groups = ((sorted(_Addon(n, TocReader_(n)) for n in k),
                   [results[i] for i in v])
                  for k, v in buckets)
        return groups

    def get_leftovers() -> Set[str]:
        addons = {f.name for f in manager.config.addon_dir.iterdir() if f.is_dir()}
        leftovers = addons - {f.name for f in manager.db_session.query(PkgFolder).all()}
        return leftovers

    def match_all():
        # Match in order of increasing heuristicitivenessitude
        for fn in (match_toc_ids_from_sources,
                   match_dir_names,):
            groups = fn(get_leftovers())
            yield [u for _, u in prompt(groups)]

    if not get_leftovers():
        click.echo('No add-ons left to reconcile.')
        return

    click.echo('''\
- Use the arrow keys to navigate, 'o' (Oscar) to open an
  add-on in your browser and enter to make a selection.
- Versions that differ from the installed version
  or differ between choices are highlighted in purple.
- instawow will do a first pass of all of your add-ons
  looking for source IDs in TOC files, e.g. X-Curse-Project-ID.
- If it is unable to reconcile all of your add-ons
  it will perform a second pass to match add-on folders
  against the CurseForge and WoWInterface catalogues.
- Selected add-ons will be reinstalled.
- This feature is experimental and very much untested.\
''')
    for selections in match_all():
        if selections and confirm_('Install selected add-ons?').unsafe_ask():
            results = list(zip(selections, install(selections)))
            Report(results).generate()
    click.echo('- Unreconciled add-ons can be listed with '
                '`instawow list-folders -e`.')


@main.command('list')
@click.option('--column', '-c', 'columns',
              multiple=True,
              help='A field to show in a column.  Nested fields are '
                   'dot-delimited.  Repeatable.')
@click.option('--columns', '-C', 'print_columns',
              is_flag=True, default=False,
              help='Print a list of all possible column values.')
@click.option('--sort-by', '-s', 'sort_key',
              default='name',
              help='A key to sort the table by.  '
                   'You can chain multiple keys by separating them with a comma '
                   'just as you would in SQL, '
                   'e.g. `--sort-by="origin, date_published DESC"`.')
@_pass_manager
def list_installed(manager, columns, print_columns, sort_key) -> None:
    "List installed add-ons."
    from operator import attrgetter
    from sqlalchemy import inspect, text

    def format_columns(pkg):
        for column in columns:
            try:
                value = attrgetter(column)(pkg)
            except AttributeError:
                raise click.BadParameter(column, param_hint=['--column', '-c'])
            if column == 'folders':
                yield '\n'.join(f.name for f in value)
            elif column == 'options':
                yield f'strategy = {value.strategy}'
            elif column == 'description':
                yield fill(value, width=50, max_lines=3)
            else:
                yield value

    if print_columns:
        columns = [('field',),
                   *((c,) for c in (*inspect(Pkg).columns.keys(),
                                    *inspect(Pkg).relationships.keys()))]
        click.echo(tabulate(columns, show_index=False))
    else:
        pkgs = manager.db_session.query(Pkg).order_by(text(sort_key)).all()
        if pkgs:
            rows = [('add-on', *columns),
                    *((Defn(p.origin, p.slug), *format_columns(p)) for p in pkgs)]
            click.echo(tabulate(rows))


@main.command()
@click.option('--exclude-own', '-e',
              is_flag=True, default=False,
              help='Exclude folders managed by instawow.')
@click.option('--toc-entry', '-t', 'toc_entries',
              multiple=True,
              help='An entry to extract from the TOC.  Repeatable.')
@_pass_manager
def list_folders(manager, exclude_own, toc_entries) -> None:
    "List add-on folders."
    folders = {f for f in manager.config.addon_dir.iterdir() if f.is_dir()}
    if exclude_own:
        folders -= {manager.config.addon_dir / f.name
                    for f in manager.db_session.query(PkgFolder).all()}

    folder_tocs = ((n, n / f'{n.name}.toc') for n in folders)
    folder_readers = sorted((n, TocReader.from_path(t)) for n, t in folder_tocs if t.exists())
    if folder_readers:
        rows = [('folder',
                 *(f'[{e}]' for e in toc_entries)),
                *((n.name,
                  *(fill(t[e].value, width=50) for e in toc_entries))
                  for n, t in folder_readers)]
        click.echo(tabulate(rows))


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@click.option('--toc-entry', '-t', 'toc_entries',
              multiple=True,
              help='An entry to extract from the TOC.  Repeatable.')
@_pass_manager
def info(manager, addon, toc_entries) -> None:
    "Show detailed add-on information."
    pkg = get_pkg_from_substr(manager, addon)
    if pkg:
        rows = {'name': pkg.name,
                'source': pkg.origin,
                'id': pkg.id,
                'slug': pkg.slug,
                'description': fill(pkg.description, max_lines=5),
                'homepage': pkg.url,
                'version': pkg.version,
                'release date': pkg.date_published,
                'folders': '\n'.join([str(manager.config.addon_dir)]
                                     + [' ├─ ' + f.name for f in pkg.folders[:-1]]
                                     + [' └─ ' + pkg.folders[-1].name]),
                'strategy': pkg.options.strategy}

        if toc_entries:
            for folder in pkg.folders:
                toc_reader = TocReader.from_path_name(manager.config.addon_dir / folder.name)
                rows.update({f'[{folder.name} {k}]': fill(toc_reader[k].value)
                             for k in toc_entries})
        click.echo(tabulate([(), *rows.items()], show_index=False))
    else:
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@_pass_manager
def visit(manager, addon) -> None:
    "Open an add-on's homepage in your browser."
    pkg = get_pkg_from_substr(manager, addon)
    if pkg:
        import webbrowser
        webbrowser.open(pkg.url)
    else:
        Report([(addon, E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@_pass_manager
def reveal(manager, addon) -> None:
    "Open an add-on folder in your file manager."
    pkg = get_pkg_from_substr(manager, addon)
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

    prompt_ = partial(prompt, complete_style=CompleteStyle.READLINE_LIKE)

    class DirectoryCompleter(PathCompleter):

        def __init__(self, *args, **kwargs):
            super().__init__(*args,
                             expanduser=True, only_directories=True, **kwargs)

        def get_completions(self, document, complete_event):
            # Append slash to every completion
            for completion in super().get_completions(document, complete_event):
                completion.text += '/'
                yield completion

    def validate_addon_dir(value: str) -> bool:
        path = os.path.expanduser(value)
        return os.path.isdir(path) and os.access(path, os.W_OK)

    completer = DirectoryCompleter()
    validator = Validator.from_callable(validate_addon_dir,
                                        error_message='must be a writable directory')
    addon_dir = prompt_('Add-on directory: ',
                        completer=completer, validator=validator)

    game_flavours = ('retail', 'classic')
    completer = WordCompleter(game_flavours)
    validator = Validator.from_callable(game_flavours.__contains__,
                                        error_message='must be one of: retail, classic')
    game_flavour = prompt_('Game flavour: ',
                           completer=completer, validator=validator)

    config = Config(addon_dir=addon_dir, game_flavour=game_flavour).write()
    click.echo(f'Configuration written to: {config.config_file}')


@main.command()
@_pass_manager
def show_config(manager) -> None:
    "Show the active configuration."
    click.echo(manager.config.json(exclude=set()))


@main.group('weakauras-companion',
            cls=_OrigCmdOrderGroup)
def _weakauras_group() -> None:
    "Manage your WeakAuras."


@_weakauras_group.command('build')
@click.option('--account', '-a',
              required=True,
              help='Your account name.  This is used to locate '
                   'the WeakAuras data file.')
@_pass_manager
def build_weakauras_companion(manager, account) -> None:
    "Build the WeakAuras Companion add-on."
    from .wa_updater import WaCompanionBuilder

    manager.run(WaCompanionBuilder(manager).build(account))


@_weakauras_group.command('list')
@click.option('--account', '-a',
              required=True,
              help='Your account name.  This is used to locate '
                   'the WeakAuras data file.')
@_pass_manager
def list_installed_wago_auras(manager, account) -> None:
    "List WeakAuras installed from Wago."
    from .wa_updater import WaCompanionBuilder

    aura_groups = WaCompanionBuilder(manager).extract_installed_auras(account)
    installed_auras = sorted((a.id, a.url, str(a.ignore_wago_update).lower())
                             for v in aura_groups.values()
                             for a in v
                             if not a.parent)
    click.echo(tabulate([('name', 'url', 'ignore updates'),
                         *installed_auras]))
