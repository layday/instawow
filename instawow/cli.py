
from __future__ import annotations

__all__ = ('main',)

from enum import Enum
from functools import partial, update_wrapper
from textwrap import fill
from typing import (TYPE_CHECKING, Any, Callable, Generator, Iterable, List,
                    NamedTuple, Optional, Sequence, Tuple, Union)

import click

from . import __version__
from .config import Config
from . import exceptions as E
from .manager import CliManager
from .models import Pkg, PkgFolder
from .resolvers import Strategies
from .utils import TocReader, bucketise, is_outdated, setup_logging


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
        else:
            return cls.SUCCESS

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
            (f'{Symbols.from_result(r)} {click.style(a, bold=True)}\n'
             f'  {r.message}')
            for a, r in self.results
            if self.filter_fn(r)
            )

    def generate_and_exit(self) -> None:
        report = str(self)
        if report:
            click.echo(report)

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


class _Parts(NamedTuple):

    origin: str
    id_or_slug: str


def compose_pkg_uri(val: Any) -> str:
    try:
        origin, slug = val.origin, val.slug
    except AttributeError:
        origin, slug = val
    return ':'.join((origin, slug))


def decompose_pkg_uri(ctx: click.Context,
                      param: click.Parameter,
                      value: Union[str, Tuple[str, ...]],
                      *,
                      raise_for_invalid_uri: bool = True) -> Tuple[str, _Parts]:
    if isinstance(value, tuple):
        return list(bucketise(decompose_pkg_uri(ctx, param, v) for v in value))

    if ':' not in value:
        if raise_for_invalid_uri:
            raise click.BadParameter(value)

        parts = _Parts('*', value)
    else:
        for resolver in ctx.obj().resolvers.values():
            parts = resolver.decompose_url(value)
            if parts:
                parts = _Parts(*parts)
                break
        else:
            parts = _Parts(*value.partition(':')[::2])
    return compose_pkg_uri(parts), parts


def validate_strategy(ctx: click.Context,
                      param: click.Parameter,
                      value: Optional[str]) -> Optional[str]:
    if value and not ctx.params['addons']:
        raise click.UsageError(f'{param.get_error_hint(ctx)} must be used'
                               ' in conjunction with "ADDONS"')
    return value


def get_pkg_from_substr(manager: CliManager, parts: _Parts) -> Optional[Pkg]:
    return manager.get(*parts) or (manager.db.query(Pkg)
                                   .filter(Pkg.slug.contains(parts.id_or_slug))
                                   .order_by(Pkg.name)
                                   .first())


class _OrigCmdOrderGroup(click.Group):

    def list_commands(self, ctx: click.Context) -> List[str]:
        # The default is ``sorted(self.commands)``
        return list(self.commands)


def _pass_manager(f: Callable) -> Callable:
    # Like ``click.pass_obj`` but calls ``obj`` before passing it on
    def new_func(*args: Any, **kwargs: Any) -> Callable:
        return f(click.get_current_context().obj(), *args, **kwargs)
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
    try:
        import uvloop
    except ImportError:
        pass
    else:
        import asyncio
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    if not ctx.obj:
        def prepare_state() -> CliManager:
            while True:
                try:
                    config = Config.read().write()
                except FileNotFoundError:
                    ctx.invoke(write_config)
                else:
                    break

            setup_logging(config, debug or 'INFO')
            manager = CliManager(config)
            if is_outdated(manager):
                click.echo(f'{Symbols.WARNING} instawow is out of date')
            return manager

        ctx.obj = prepare_state


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=decompose_pkg_uri)
@click.option('--strategy', '-s',
              type=click.Choice({s.value for s in Strategies}),
              default='default',
              help="Whether to install the latest published version "
                   "('default') or the very latest upload ('latest').")
@click.option('--replace', '-o',
              is_flag=True, default=False,
              help='Replace existing add-ons.')
@_pass_manager
def install(manager, addons, strategy, replace) -> None:
    "Install add-ons."
    results = zip((a for a, _ in addons),
                  manager.install((p for _, p in addons), strategy, replace))
    Report(list(results)).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, callback=decompose_pkg_uri, is_eager=True)
@_pass_manager
def update(manager, addons) -> None:
    "Update installed add-ons."
    orig_addons = addons
    if not addons:
        addons = [(compose_pkg_uri(p), (p.origin, p.slug))
                  for p in manager.db.query(Pkg).all()]

    results = zip((a for a, _ in addons),
                  manager.update(p for _, p in addons))
    # Hide if ``update`` was invoked without arguments
    # and the package is up-to-date
    filter_fn = lambda r: orig_addons or not isinstance(r, E.PkgUpToDate)
    Report(list(results), filter_fn).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=decompose_pkg_uri)
@_pass_manager
def remove(manager, addons) -> None:
    "Uninstall add-ons."
    results = zip((a for a, _ in addons), manager.remove(p for _, p in addons))
    Report(list(results)).generate_and_exit()


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
        pkgs = manager.db.query(Pkg).order_by(text(sort_key)).all()
        if pkgs:
            rows = [('add-on', *columns),
                    *((compose_pkg_uri(p), *format_columns(p)) for p in pkgs)]
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
                    for f in manager.db.query(PkgFolder).all()}

    folder_tocs = ((n, n / f'{n.name}.toc') for n in folders)
    folder_readers = sorted((n, TocReader.from_path(t)) for n, t in folder_tocs if t.exists())
    if folder_readers:
        rows = [('folder', 'Curse ID', 'WoWI ID',
                 *(f'[{e}]' for e in toc_entries)),
                *((n.name,
                   t['X-Curse-Project-ID'].value,
                   t['X-WoWI-ID'].value,
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
    pkg = get_pkg_from_substr(manager, addon[1])
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
        Report([(addon[0], E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@_pass_manager
def visit(manager, addon) -> None:
    "Open an add-on's homepage in your browser."
    pkg = get_pkg_from_substr(manager, addon[1])
    if pkg:
        import webbrowser
        webbrowser.open(pkg.url)
    else:
        Report([(addon[0], E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@_pass_manager
def reveal(manager, addon) -> None:
    "Open an add-on folder in your file manager."
    pkg = get_pkg_from_substr(manager, addon[1])
    if pkg:
        import webbrowser
        webbrowser.open((manager.config.addon_dir / pkg.folders[0].name).as_uri())
    else:
        Report([(addon[0], E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.pass_context
def write_config(ctx) -> None:
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


@main.group('extras',
            cls=_OrigCmdOrderGroup)
def _extras_group() -> None:
    "Additional functionality."


@_extras_group.group('weakauras',
                     cls=_OrigCmdOrderGroup)
def _weakauras_group() -> None:
    "Manage your WeakAuras."


@_weakauras_group.command('build-companion')
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


@main.command(hidden=True)
@click.option('--port', type=int, help='The server port.')
def web_serve(port) -> None:
    "Run the WebSocket server."
    from .manager import WsManager
    WsManager().serve(port=port)
