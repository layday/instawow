
from __future__ import annotations

__all__ = ('main',)

from enum import Enum
from functools import partial, reduce
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
            (f'{Symbols.from_result(r).value} {click.style(a, bold=True)}\n'
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
        rows = iter(rows)
        rows = [('', *next(rows)), *((i, *v) for i, v in enumerate(rows, start=1))]
        table.set_cols_align(('r', *('l' for _ in rows[0]))[:-1])
    else:
        rows = [(), *rows]

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
        return list(bucketise(decompose_pkg_uri(ctx, param, v)
                              for v in value).keys())

    if ':' not in value:
        if raise_for_invalid_uri:
            raise click.BadParameter(value)

        parts = _Parts('*', value)
    else:
        for resolver in ctx.obj.resolvers.values():
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
        return list(self.commands)    # The default is ``sorted(self.commands)``


def create_config() -> Config:
    """Create the configuration.  This prompts the user for their add-on folder
    on first run or if the folder can't be found.
    """
    try:
        return Config().write()
    except E.ConfigError as error:
        # readline is picked up by ``input`` to undumbify line editing
        import readline

        # Don't bother if Python was built without GNU readline - we'd have to
        # reimplement path completion
        if 'GNU readline' in getattr(readline, '__doc__', ''):
            readline.parse_and_bind('tab: complete')
            readline.set_completer_delims('')   # Do not split up the string

        message = (
            f'{Symbols.WARNING.value} {{.message}}\n'
            f'  {click.style(">", fg="yellow")} enter the path to your add-on folder: ')

        def prompt(error: E.ConfigError) -> Config:
            try:
                addon_dir = input(message.format(error))
            except E.ConfigError as error:
                return prompt(error)
            else:
                return Config(addon_dir=addon_dir).write()

        return prompt(error)


@click.group(cls=_OrigCmdOrderGroup,
             context_settings={'help_option_names': ['-h', '--help']})
@click.version_option(__version__, prog_name='instawow')
@click.pass_context
def main(ctx):
    "Add-on manager for World of Warcraft."
    try:
        import uvloop
    except ImportError:
        pass
    else:
        import asyncio
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    if not ctx.obj and ctx.invoked_subcommand != 'serve':
        config = create_config()
        setup_logging(config)

        if ctx.invoked_subcommand == 'extras':
            ctx.obj = CliManager(config, show_progress=False)
        else:
            ctx.obj = manager = CliManager(config)
            if is_outdated(manager):
                click.echo(f'{Symbols.WARNING.value} instawow is out of date')


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
@click.pass_obj
def install(manager, addons, strategy, replace) -> None:
    "Install add-ons."
    results = zip((d for d, _ in addons),
                  manager.install_many((*p, strategy, replace) for _, p in addons))
    Report(list(results)).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, callback=decompose_pkg_uri, is_eager=True)
@click.option('--strategy', '-s',
              callback=validate_strategy,
              type=click.Choice({s.value for s in Strategies}),
              default=None,
              help="Whether to update to the latest published version "
                   "('default') or the very latest upload ('latest').")
@click.pass_obj
def update(manager, addons, strategy) -> None:
    "Update installed add-ons."
    orig_addons = addons
    if not addons:
        addons = [(compose_pkg_uri(p), (p.origin, p.slug))
                  for p in manager.db.query(Pkg).all()]

    if strategy:
        with manager.db.begin_nested():
            for pkg in (manager.get(*p) for _, p in addons):
                pkg.options.strategy = strategy

    results = zip((d for d, _ in addons),
                  manager.update_many(p for _, p in addons))
    # Hide if ``update`` was invoked without arguments and the package is
    # up-to-date or temporarily unavailable
    filter_fn = lambda r: (orig_addons
                           or not isinstance(r, (E.PkgUpToDate, E.PkgTemporarilyUnavailable)))
    Report(list(results), filter_fn).generate_and_exit()


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=decompose_pkg_uri)
@click.pass_obj
def remove(manager, addons) -> None:
    "Uninstall add-ons."
    def remove_():
        for addon, parts in addons:
            try:
                yield (addon, manager.run(manager.remove(*parts)))
            except (E.ManagerError, E.InternalError) as error:
                yield (addon, error)

    Report(list(remove_())).generate_and_exit()


@main.command('list')
@click.option('--column', '-c', 'columns',
              multiple=True,
              help='A field to show in a column.  Nested fields are '
                   'dot-delimited.  Repeatable.')
@click.option('--columns', '-C', 'print_columns',
              is_flag=True, default=False,
              help='Print a list of all possible column values.')
@click.option('--toc-entry', '-t', 'toc_entries',
              multiple=True,
              help='An entry to extract from the TOC.  Repeatable.')
@click.option('--sort-by', '-s', 'sort_key',
              default='name',
              help='A key to sort the table by.  '
                   'You can chain multiple keys by separating them with a comma '
                   'just as you would in SQL, '
                   'e.g. `--sort-by="origin, date_published DESC"`.')
@click.pass_obj
def list_installed(manager, columns, print_columns, toc_entries, sort_key) -> None:
    "List installed add-ons."
    from sqlalchemy import inspect, text

    def format_columns(pkg):
        for column in columns:
            try:
                value = reduce(getattr, [pkg] + column.split('.'))
            except AttributeError:
                raise click.BadParameter(column, param_hint=['--column', '-c'])
            if column == 'folders':
                value = '\n'.join(f.name for f in value)
            elif column == 'options':
                value = f'strategy = {value.strategy}'
            elif column == 'description':
                value = fill(value, width=50, max_lines=3)
            yield value

    def format_toc_entries(pkg):
        if toc_entries:
            toc_readers = [TocReader(manager.config.addon_dir
                                     / f.name
                                     / f'{f.name}.toc') for f in pkg.folders]
            for toc_entry in toc_entries:
                value = [fill(r[toc_entry].value, width=50) for r in toc_readers]
                value = sorted(set(value), key=value.index)
                yield '\n'.join(value)

    if print_columns:
        rows = [('field',),
                *((c,) for c in (*inspect(Pkg).columns.keys(),
                                 *inspect(Pkg).relationships.keys()))]
        click.echo(tabulate(rows, show_index=False))
    else:
        pkgs = manager.db.query(Pkg).order_by(text(sort_key)).all()
        if pkgs:
            rows = [('add-on', *columns, *(f'[{e}]' for e in toc_entries)),
                     *((compose_pkg_uri(p), *format_columns(p), *format_toc_entries(p))
                    for p in pkgs)]
            click.echo(tabulate(rows))


@main.command()
@click.pass_obj
def list_uncontrolled(manager) -> None:
    "List add-ons not managed by instawow."
    folders = ({f for f in manager.config.addon_dir.iterdir() if f.is_dir()}
               - {manager.config.addon_dir / f.name
                  for f in manager.db.query(PkgFolder).all()})
    folders_and_tocs = ((n, n / f'{n.name}.toc') for n in folders)
    folders_and_readers = sorted((n, TocReader(t))
                                 for n, t in folders_and_tocs if t.exists())
    if folders:
        rows = [('folder', 'Curse ID', 'WoWI ID', 'version'),
                *((n.name,
                   t['X-Curse-Project-ID'].value,
                   t['X-WoWI-ID'].value,
                   t['X-Curse-Packaged-Version', 'X-Packaged-Version', 'Version'].value)
                  for n, t in folders_and_readers)]
        click.echo(tabulate(rows))


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@click.option('--toc-entry', '-t', 'toc_entries',
              multiple=True,
              help='An entry to extract from the TOC.  Repeatable.')
@click.pass_obj
def info(manager, addon, toc_entries) -> None:
    "Show the details of an installed add-on."
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
                toc_reader = TocReader(manager.config.addon_dir
                                       / folder.name
                                       / f'{folder.name}.toc')
                rows.update({f'[{folder.name} {k}]': fill(toc_reader[k].value)
                             for k in toc_entries})
        click.echo(tabulate(rows.items(), show_index=False))
    else:
        Report([(addon[0], E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@click.pass_obj
def visit(manager, addon) -> None:
    "Open the add-on's homepage in your browser."
    pkg = get_pkg_from_substr(manager, addon[1])
    if pkg:
        import webbrowser
        webbrowser.open(pkg.url)
    else:
        Report([(addon[0], E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.argument('addon', callback=partial(decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@click.pass_obj
def reveal(manager, addon) -> None:
    "Open the add-on folder in your file manager."
    pkg = get_pkg_from_substr(manager, addon[1])
    if pkg:
        import webbrowser
        webbrowser.open((manager.config.addon_dir / pkg.folders[0].name).as_uri())
    else:
        Report([(addon[0], E.PkgNotInstalled())]).generate_and_exit()


@main.command()
@click.option('--port', type=int, help='The server port.')
def serve(port) -> None:
    "Run the WebSocket server."
    from .manager import WsManager
    WsManager().serve(port=port)


@main.group('extras',
            cls=_OrigCmdOrderGroup)
def _extras_group() -> None:
    "Additional functionality."


@_extras_group.group('weakauras',
                     cls=_OrigCmdOrderGroup)
def _weakauras_group() -> None:
    "Manage your WeakAuras."


@_extras_group.group('bitbar',
                     cls=_OrigCmdOrderGroup)
def _bitbar_group() -> None:
    """Mini update GUI implemented as a BitBar plug-in.

    BitBar <https://getbitbar.com/> is a menu-bar app host for macOS.
    """


@_bitbar_group.command('_generate', hidden=True)
@click.argument('caller')
@click.argument('version')
@click.pass_obj
def generate_bitbar_output(manager, caller, version):
    from base64 import b64encode
    from pathlib import Path
    from subprocess import run, PIPE

    installed = manager.db.query(Pkg).order_by(Pkg.name).all()
    latest = manager.resolve_many((p.origin, p.id, p.options.strategy) for p in installed)
    outdated = [(l, r) for l, r in zip(installed, latest)
                if l.file_id != getattr(r, 'file_id', l.file_id)]

    icon = Path(__file__).parent / 'assets' / f'''\
NSStatusItem-icon__\
{"has-updates" if outdated else "clear"}\
{"@2x" if b"Retina" in run(("system_profiler", "SPDisplaysDataType"),
                           stdout=PIPE).stdout else ""}\
.png'''
    icon = b64encode(icon.read_bytes()).decode()

    click.echo(f'''| templateImage="{icon}"
---
instawow ({__version__}:{version})''')
    if outdated:
        if len(outdated) > 1:
            click.echo(f'''\
Update all | bash={caller} param1=update terminal=false refresh=true''')
        for p, r in outdated:
            click.echo(f'''\
Update “{r.name}” ({p.version} ➞ {r.version}) | \
  refresh=true \
  bash={caller} param1=update param2={_compose_pkg_uri(r)} terminal=false
View “{r.name}” on {manager.resolvers[r.origin].name} | \
  alternate=true \
  bash={caller} param1=hearth param2={_compose_pkg_uri(r)} terminal=false''')


@_bitbar_group.command('install')
def install_bitbar_plugin():
    "Install the instawow BitBar plug-in."
    from pathlib import Path
    import sys
    import tempfile
    import webbrowser

    with tempfile.TemporaryDirectory() as name:
        path = Path(name, 'instawow.1h.py')
        path.write_text(f'''\
#!/usr/bin/env LC_ALL=en_US.UTF-8 {sys.executable}

__version__ = {__version__!r}

import sys

from instawow.cli import main

main(['-n', *(sys.argv[1:] or ['extras', 'bitbar', '_generate', sys.argv[0], __version__])])
''')
        webbrowser.open(f'bitbar://openPlugin?src={path.as_uri()}')
        click.pause('Press any key to exit after installing the plug-in')


@_weakauras_group.command('build-companion')
@click.option('--account', '-a',
              required=True,
              help='Your account name.  This is used to locate '
                   'the WeakAuras data file.')
@click.pass_obj
def build_weakauras_companion(manager, account) -> None:
    "Build the WeakAuras Companion add-on."
    from .wa_updater import WaCompanionBuilder
    WaCompanionBuilder(manager).build(account)


@_weakauras_group.command('list')
@click.option('--account', '-a',
              required=True,
              help='Your account name.  This is used to locate '
                   'the WeakAuras data file.')
@click.pass_obj
def list_installed_wago_auras(manager, account) -> None:
    "List WeakAuras installed from Wago."
    from .wa_updater import WaCompanionBuilder

    aura_groups = WaCompanionBuilder(manager).extract_installed_auras(account)
    installed_auras = [(a.url, str(a.ignore_wago_update).lower())
                       for a, *_ in aura_groups.values()]
    click.echo(tabulate([('url', 'ignore updates'), *installed_auras]))
