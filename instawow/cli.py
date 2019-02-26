
from __future__ import annotations

from functools import partial, reduce
from itertools import count
from textwrap import fill
from typing import Any, List, NamedTuple, Optional, Tuple, Union

import click
import logbook
from sqlalchemy import inspect, text
from texttable import Texttable

from . import __version__
from .config import Config
from . import exceptions as E
from .manager import CliManager
from .models import Pkg, PkgFolder
from .utils import TocReader, is_outdated


__all__ = ('cli',)


_CONTEXT_SETTINGS = {'help_option_names': ['-h', '--help']}

_SUCCESS = click.style('✓', fg='green')
_FAILURE = click.style('✗', fg='red')
_WARNING = click.style('!', fg='blue')


def _format_result(addon: str, result: E.ManagerResult) -> str:
    return f'''\
{next(s for t, s in [(E.InternalError, _WARNING),
                     (E.ManagerError,  _FAILURE),
                     (E.ManagerResult, _SUCCESS)]
      if isinstance(result, t))} \
{click.style(addon, bold=True)}
  {result.message}'''


def _tabulate(rows: List[tuple], *,
              head: tuple=(), show_index: bool=True) -> str:
    table = Texttable(max_width=0).set_deco(Texttable.VLINES |
                                            Texttable.BORDER |
                                            Texttable.HEADER)
    if show_index:
        table.set_cols_align(f'r{"l" * len(rows[0])}')
        head = ('', *head)
        rows = [(i, *v) for i, v in enumerate(rows, start=1)]
    return table.add_rows([head, *rows]).draw()


class _Parts(NamedTuple):

    origin: str
    id_or_slug: str


def _compose_pkg_uri(val: Any) -> str:
    try:
        origin, slug = val.origin, val.slug
    except AttributeError:
        origin, slug = val
    return ':'.join((origin, slug))


def _decompose_pkg_uri(ctx: click.Context, param: click.Parameter, value: Any, *,
                       raise_for_invalid_uri: bool=True) -> tuple:
    if isinstance(value, tuple):
        return tuple(_decompose_pkg_uri(ctx, param, v)
                     for v in sorted(set(value), key=value.index))

    for resolver in ctx.obj.resolvers.values():
        parts = resolver.decompose_url(value)
        if parts:
            parts = _Parts(*parts)
            break
    else:
        if ':' not in value:
            if raise_for_invalid_uri:
                raise click.BadParameter(value)
            parts = _Parts('*', value)
        else:
            parts = _Parts(*value.partition(':')[::2])
    return _compose_pkg_uri(parts), parts


def _get_pkg_from_substr(manager: CliManager, pkg: _Parts) -> Optional[Pkg]:
    return manager.get(*pkg) or \
        manager.db.query(Pkg).filter(Pkg.slug.contains(pkg.id_or_slug))\
                             .order_by(Pkg.name)\
                             .first()


class _OrigCmdOrderGroup(click.Group):

    def list_commands(self, ctx):
        return list(self.commands)    # The default is ``sorted(self.commands)``


def _init():
    addon_dir = click.prompt('Enter the path to your add-on folder')
    while True:
        try:
            Config(addon_dir=addon_dir).write()
        except ValueError:
            addon_dir = click.prompt(f'{addon_dir} not found\n'
                                      'Enter the path to your add-on folder')
        else:
            break


@click.group(cls=_OrigCmdOrderGroup, context_settings=_CONTEXT_SETTINGS)
@click.version_option(__version__, prog_name='instawow')
@click.option('--hide-progress', '-n', is_flag=True, default=False, hidden=True,
              help='Hide the progress bar.')
@click.pass_context
def main(ctx, hide_progress):
    "Add-on manager for World of Warcraft."
    if not ctx.obj:
        for attempt in count():
            try:
                config = Config()
            except (FileNotFoundError, ValueError):
                _init()
            else:
                break
        ctx.obj = manager = CliManager(config=config,
                                       show_progress=not hide_progress)
        if attempt:
            # Migrate add-on paths after redefining ``addon_dir``
            for folder in manager.db.query(PkgFolder).all():
                folder.path = manager.config.addon_dir / folder.path.name
            manager.db.commit()

        logbook.RotatingFileHandler(manager.config.config_dir / 'error.log',
                                    delay=True)\
               .push_application()

        if is_outdated(manager):
            click.echo(f'{_WARNING} instawow is out of date')

cli = main


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=_decompose_pkg_uri)
@click.option('--strategy', '-s',
              type=click.Choice(['canonical', 'latest']),
              default='canonical',
              help="Whether to install the latest published version "
                   "('canonical') or the very latest upload ('latest').")
@click.option('--overwrite', '-o',
              is_flag=True, default=False,
              help='Overwrite existing add-ons.')
@click.pass_obj
def install(manager, addons, overwrite, strategy):
    "Install add-ons."
    for addon, result in zip((d for d, _ in addons),
                             manager.install_many((*p, strategy, overwrite)
                                                  for _, p in addons)):
        click.echo(_format_result(addon, result))


@main.command()
@click.argument('addons', nargs=-1, callback=_decompose_pkg_uri)
@click.option('--strategy', '-s',
              type=click.Choice(['canonical', 'latest']), default=None,
              help="Whether to update to the latest published version "
                   "('canonical') or the very latest upload ('latest').")
@click.pass_obj
def update(manager, addons, strategy):
    "Update installed add-ons."
    orig_addons = addons
    if not addons:
        addons = [(_compose_pkg_uri(p), (p.origin, p.slug))
                  for p in manager.db.query(Pkg).all()]
    if strategy:
        for pkg in (manager.get(*p) for _, p in addons):
            pkg.options.strategy = strategy
        manager.db.commit()

    for addon, result in zip((d for d, _ in addons),
                             manager.update_many(p for _, p in addons)):
        if not (not orig_addons and
                isinstance(result, (E.PkgUpToDate, E.PkgTemporarilyUnavailable))):
            click.echo(_format_result(addon, result))


@main.command()
@click.argument('addons', nargs=-1, required=True, callback=_decompose_pkg_uri)
@click.pass_obj
def remove(manager, addons):
    "Uninstall add-ons."
    for addon, parts in addons:
        try:
            result = manager.loop.run_until_complete(manager.remove(*parts))
        except (E.ManagerError, E.InternalError) as error:
            result = error
        click.echo(_format_result(addon, result))


@main.group('list')
def list_():
    "List add-ons."


@list_.command('installed')
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
def list_installed(manager,
                   columns, print_columns, toc_entries,
                   sort_key):
    "List installed add-ons."
    def format_columns(pkg):
        for column in columns:
            try:
                value = reduce(getattr, [pkg] + column.split('.'))
            except AttributeError:
                raise click.BadParameter(column,
                                         param_hint=['--column', '-c'])
            if column == 'folders':
                value = '\n'.join(f.path.name for f in value)
            elif column == 'options':
                value = {'strategy': value.strategy}
            elif column == 'description':
                value = fill(value, width=50, max_lines=3)
            yield value

    def format_toc_entries(pkg):
        toc_readers = [TocReader(f.path / f'{f.path.name}.toc')
                       for f in pkg.folders]
        for toc_entry in toc_entries:
            value = [fill(r[toc_entry].value or '', width=50)
                     for r in toc_readers]
            value = sorted(set(value), key=value.index)
            value = '\n'.join(value)
            yield value

    if print_columns:
        click.echo(_tabulate([(c,) for c in (*inspect(Pkg).columns.keys(),
                                             *inspect(Pkg).relationships.keys())],
                             head=('field',), show_index=False))
    else:
        click.echo(_tabulate([(_compose_pkg_uri(p),
                               *format_columns(p),
                               *format_toc_entries(p))
                              for p in manager.db.query(Pkg)
                                                 .order_by(text(sort_key))
                                                 .all()],
                             head=('add-on',
                                   *columns,
                                   *(f'[{e}]' for e in toc_entries))))


@list_.command('outdated')
@click.option('--flip', '-f', 'should_flip',
              is_flag=True, help='Check against the opposing strategy.')
@click.pass_obj
def list_outdated(manager, should_flip):
    "List outdated add-ons."
    def flip(strategy):
        if should_flip:
            strategy = 'latest' if strategy == 'canonical' else 'canonical'
        return strategy

    all_pkgs = manager.db.query(Pkg).order_by(Pkg.name).all()
    outdated = zip(all_pkgs,
                   manager.resolve_many((p.origin, p.id, flip(p.options.strategy))
                                        for p in all_pkgs))
    outdated = [(i, n) for i, n in outdated if i.file_id != n.file_id
                if isinstance(n, Pkg)]
    if outdated:
        click.echo(_tabulate([(_compose_pkg_uri(n),
                               i.version, n.version, n.options.strategy)
                              for i, n in outdated],
                             head=('add-on', 'installed', 'new', 'strategy')))


@list_.command('preexisting')
@click.pass_obj
def list_preexisting(manager):
    "List add-ons not installed by instawow."
    folders = {f.name
               for f in manager.config.addon_dir.iterdir() if f.is_dir()} - \
              {f.path.name for f in manager.db.query(PkgFolder).all()}
    folders = ((n, manager.config.addon_dir / n / f'{n}.toc') for n in folders)
    folders = {(n, TocReader(t)) for n, t in folders if t.exists()}
    if folders:
        click.echo(_tabulate([(n,
                               t['X-Curse-Project-ID'].value or '',
                               t['X-WoWI-ID'].value or '',
                               t['X-Curse-Packaged-Version', 'X-Packaged-Version',
                                 'Version'].value or '')
                              for n, t in sorted(folders)],
                             head=('folder', 'Curse ID', 'WoWI ID', 'version')))


@main.command()
@click.argument('addon', callback=partial(_decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@click.option('--toc-entry', '-t', 'toc_entries',
              multiple=True,
              help='An entry to extract from the TOC.  Repeatable.')
@click.pass_obj
def info(manager, addon, toc_entries):
    "Show the details of an installed add-on."
    pkg = _get_pkg_from_substr(manager, addon[1])
    if pkg:
        rows = {'name': pkg.name,
                'source': pkg.origin,
                'id': pkg.id,
                'slug': pkg.slug,
                'description': fill(pkg.description, max_lines=5),
                'homepage': pkg.url,
                'version': pkg.version,
                'release date': pkg.date_published,
                'folders': '\n'.join([str(pkg.folders[0].path.parent)] +
                                     [' ├─ ' + f.path.name for f in pkg.folders[:-1]] +
                                     [' └─ ' + pkg.folders[-1].path.name]),
                'strategy': pkg.options.strategy,}

        if toc_entries:
            for path, toc_reader in ((f.path,
                                      TocReader(f.path / f'{f.path.name}.toc'))
                                     for f in pkg.folders):
                rows.update({f'[{path.name} {k}]': fill(toc_reader[k].value or '')
                             for k in toc_entries})
        click.echo(_tabulate(rows.items(), show_index=False))
    else:
        click.echo(_format_result(addon[0], E.PkgNotInstalled()))


@main.command()
@click.argument('addon', callback=partial(_decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@click.pass_obj
def hearth(manager, addon):
    "Open the add-on's homepage in your browser."
    pkg = _get_pkg_from_substr(manager, addon[1])
    if pkg:
        import webbrowser
        webbrowser.open(pkg.url)
    else:
        click.echo(_format_result(addon[0], E.PkgNotInstalled()))


@main.command()
@click.argument('addon', callback=partial(_decompose_pkg_uri,
                                          raise_for_invalid_uri=False))
@click.pass_obj
def reveal(manager, addon):
    "Open the add-on folder in your file manager."
    pkg = _get_pkg_from_substr(manager, addon[1])
    if pkg:
        import webbrowser
        webbrowser.open(pkg.folders[0].path.as_uri())
    else:
        click.echo(_format_result(addon[0], E.PkgNotInstalled()))


@main.group()
def extras():
    "Additional functionality."


@extras.group()
def bitbar():
    """Mini update GUI implemented as a BitBar plug-in.

    BitBar <https://getbitbar.com/> is a menu-bar app host for macOS.
    """


@bitbar.command('_generate', hidden=True)
@click.argument('caller')
@click.argument('version')
@click.pass_obj
def bitbar_generate(manager, caller, version):
    from base64 import b64encode
    from pathlib import Path
    from subprocess import run, PIPE

    outdated = manager.db.query(Pkg).order_by(Pkg.name).all()
    outdated = zip(outdated,
                   manager.resolve_many((p.origin, p.id, p.options.strategy)
                                        for p in outdated))
    outdated = [(p, r) for p, r in outdated
                if p.file_id != getattr(r, 'file_id', p.file_id)]

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


@bitbar.command('install')
def bitbar_install():
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


@extras.group()
def weakauras():
    "Manage your WeakAuras."


@weakauras.command()
@click.pass_obj
def build_companion(manager):
    "Build the WeakAuras Companion add-on."
    from .wa_updater import WaCompanionBuilder
    manager.run(WaCompanionBuilder(manager).build())


@main.command()
@click.option('--port', default=55437, help='The server port.')
@click.pass_obj
def serve(cli_manager, port):
    "Run the WebSocket server."
    from .manager import WsManager

    click.echo(f'Listening at http://0.0.0.0:{port}/')
    ws_manager = WsManager(config=cli_manager.config)
    ws_manager.serve(port=port)
