
from collections import namedtuple
from functools import reduce
from textwrap import fill
import traceback
import typing as T
import webbrowser

import click
from sqlalchemy import inspect
from texttable import Texttable

from . import __version__
from .config import UserConfig
from .manager import Manager
from .models import Pkg, PkgFolder
from .utils import TocReader


_SUCCESS = click.style('✓', fg='green')
_FAILURE = click.style('✗', fg='red')

MESSAGES = {
    Manager.PkgNonexistent:
        f'{_FAILURE} {{}}: no such project id or slug'.format,
    Manager.PkgNotInstalled:
        f'{_FAILURE} {{}}: not installed'.format,
    Manager.PkgConflictsWithInstalled:
        lambda a, r: f'{_FAILURE} {a}: conflicts with installed '
                     f'add-on {_compose_addon_defn(r.conflicting_pkg)}',
    Manager.CacheObsolete:
        f'{_FAILURE} {{}}: the internal resolver cache is obsolete\n'
         '  run `instawow debug cache invalidate` and try again'
        .format,
    Manager.PkgInstalled:
        f'{_SUCCESS} {{}}: installed {{.new_pkg.version}}'.format,
    Manager.PkgAlreadyInstalled:
        f'{_FAILURE} {{}}: already installed'.format,
    Manager.PkgOriginInvalid:
        f'{_FAILURE} {{}}: invalid origin'.format,
    Manager.PkgConflictsWithPreexisting:
        f'{_FAILURE} {{}}: conflicts with an add-on not installed by instawow\n'
         '  pass `-o` to `install` if you do actually wish to overwrite this add-on'
        .format,
    Manager.PkgUpdated:
        f'{_SUCCESS} {{0}}: updated from {{1.old_pkg.version}} to {{1.new_pkg.version}}'.format,
    Manager.PkgRemoved:
        f'{_SUCCESS} {{}}: removed'.format,
    Manager.PkgModified:
        f'{_SUCCESS} {{}}: {{}} set to {{}}'.format,}

_CONTEXT_SETTINGS = {'help_option_names': ['-h', '--help']}
_SEP = ':'

_parts = namedtuple('Parts', 'origin id_or_slug')


def _tabulate(rows: T.List[T.Tuple[str, ...]], *,
              head: T.Tuple[str, ...]=(), show_index: bool=True) -> str:
    table = Texttable(max_width=0)
    table.set_chars('   -')
    table.set_deco(Texttable.HEADER | Texttable.VLINES)

    if show_index:
        table.set_cols_align(('r', *('l' for _ in rows[0])))
        head = ('', *head)
        rows = [(i, *v) for i, v in enumerate(rows, start=1)]
    table.add_rows([head, *rows])
    return table.draw()


def _compose_addon_defn(val):
    try:
        origin, slug = val.origin, val.slug
    except AttributeError:
        origin, slug = val
    return _SEP.join((origin, slug))


def _decompose_addon_defn(ctx, param, value):
    if isinstance(value, tuple):
        return [_decompose_addon_defn(ctx, param, v) for v in value]
    for resolver in ctx.obj.resolvers.values():
        parts = resolver.decompose_url(value)
        if parts:
            parts = _parts(*parts)
            break
    else:
        if _SEP not in value:
            raise click.BadParameter(value)
        parts = value.partition(_SEP)
        parts = _parts(parts[0], parts[-1])
    return _compose_addon_defn(parts), parts


def _init():
    addon_dir = UserConfig.default_addon_dir
    while True:
        try:
            UserConfig(addon_dir=addon_dir).create_dirs().write()
        except ValueError:
            if addon_dir:
                print(f'{addon_dir!r} not found')
            addon_dir = click.prompt('Please enter the path to your add-on folder')
        else:
            break

init = click.Command(name='instawow-init', callback=_init,
                     context_settings=_CONTEXT_SETTINGS)


@click.group(context_settings=_CONTEXT_SETTINGS)
@click.version_option(__version__)
@click.option('--hide-progress', '-n', is_flag=True, default=False)
@click.pass_context
def main(ctx, hide_progress):
    """Add-on manager for World of Warcraft."""
    if not ctx.obj:
        while True:
            try:
                config = UserConfig.read()
            except (FileNotFoundError, ValueError):
                _init()
            else:
                break
        ctx.obj = manager = Manager(config=config, show_progress=not hide_progress)
        ctx.call_on_close(manager.close)

cli = main


@main.command()
@click.argument('addons', nargs=-1, callback=_decompose_addon_defn)
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
    """Install add-ons."""
    for addon, result in zip((d for d, _ in addons),
                             manager.install_many((*p, strategy, overwrite)
                                                  for _, p in addons)):
        try:
            raise result
        except Manager.ManagerResult as result:
            print(MESSAGES[result.__class__](addon, result))
        except Exception:
            print(traceback.format_exc())


@main.command()
@click.argument('addons', nargs=-1, callback=_decompose_addon_defn)
@click.pass_obj
def update(manager, addons):
    """Update installed add-ons."""
    if not addons:
        addons = [(_compose_addon_defn(p), (p.origin, p.id))
                  for p in manager.db.query(Pkg).order_by(Pkg.slug).all()]
    for addon, result in zip((d for d, _ in addons),
                             manager.update_many(p for _, p in addons)):
        try:
            raise result
        except Manager.PkgUpToDate:
            pass
        except Manager.ManagerResult as result:
            print(MESSAGES[result.__class__](addon, result))
        except Exception:
            print(traceback.format_exc())


@main.command()
@click.argument('addons', nargs=-1, callback=_decompose_addon_defn)
@click.pass_obj
def remove(manager, addons):
    """Uninstall add-ons."""
    for addon, parts in addons:
        try:
            raise manager.remove(*parts)
        except Manager.ManagerResult as result:
            print(MESSAGES[result.__class__](addon, result))
        except Exception:
            print(traceback.format_exc())


@main.group('list')
def list_():
    """List add-ons."""


@list_.command()
@click.option('--column', '-c',
              multiple=True,
              help='A field to show in a column.  Nested fields are '
                   'dot-delimited.  Can be repeated.')
@click.option('--columns', '-C',
              is_flag=True, default=False,
              help='Print a list of all possible column values.')
@click.pass_obj
def installed(manager, column, columns):
    """List installed add-ons."""
    def _format_columns(pkg, columns):
        for column in columns:
            value = reduce(getattr, [pkg] + column.split('.'))
            if column == 'folders':
                value = '\n'.join(f.path.name for f in value)
            elif column == 'options':
                value = f'strategy = {value.strategy}'
            elif column == 'description':
                value = fill(value, width=50)
            yield value

    if columns:
        print(_tabulate([(c,) for c in (*inspect(Pkg).columns.keys(),
                                        *inspect(Pkg).relationships.keys())],
                         head=('field',), show_index=False))
    else:
        pkgs = manager.db.query(Pkg).order_by(Pkg.origin, Pkg.slug).all()
        if not pkgs:
            return
        try:
            print(_tabulate([(_compose_addon_defn(p),
                              *_format_columns(p, column)) for p in pkgs],
                             head=('add-on', *column)))
        except AttributeError as e:
            raise click.BadParameter(e.args)


@list_.command()
@click.pass_obj
def outdated(manager):
    """List outdated add-ons."""
    installed = manager.db.query(Pkg).order_by(Pkg.origin, Pkg.slug).all()
    new = manager.resolve_many((p.origin, p.id, p.options.strategy)
                               for p in installed)
    outdated = [(p, r) for p, r in zip(installed, new)
                if p.file_id != getattr(r, 'file_id', p.file_id)]
    if outdated:
        print(_tabulate([(_compose_addon_defn(r),
                          p.version, r.version, r.options.strategy)
                         for p, r in outdated],
                        head=('add-on', 'current version',
                              'new version', 'strategy')))


@list_.command()
@click.pass_obj
def preexisting(manager):
    """List add-ons not installed by instawow."""
    folders = {f.name
               for f in manager.config.addon_dir.iterdir() if f.is_dir()} - \
              {f.path.name for f in manager.db.query(PkgFolder).all()}
    folders = ((n, manager.config.addon_dir/n/f'{n}.toc') for n in folders)
    folders = {(n, TocReader(t)) for n, t in folders if t.exists()}
    if folders:
        print(_tabulate([(n,
                          t['X-Curse-Project-ID'].value,
                          t['X-Curse-Packaged-Version', 'X-Packaged-Version',
                            'Version'].value) for n, t in sorted(folders)],
                        head=('folder', 'curse id or slug', 'version')))


@main.command('set')
@click.argument('addons', nargs=-1, callback=_decompose_addon_defn)
@click.option('--strategy', '-s',
              type=click.Choice(['canonical', 'latest']),
              help="Whether to fetch the latest published version "
                   "('canonical') or the very latest upload ('latest').")
@click.pass_obj
def set_(manager, addons, strategy):
    """Modify add-on settings."""
    for addon in addons:
        pkg = addon[1]
        pkg = Pkg.unique(pkg.origin, pkg.id_or_slug, manager.db)
        if pkg:
            pkg.options.strategy = strategy
            manager.db.commit()
            print(MESSAGES[Manager.PkgModified](addon[0], 'strategy', strategy))
        else:
            print(MESSAGES[Manager.PkgNotInstalled](addon[0]))


@main.command()
@click.argument('addon', callback=_decompose_addon_defn)
@click.pass_obj
def info(manager, addon):
    """Display installed add-on information."""
    pkg = addon[1]
    pkg = Pkg.unique(pkg.origin, pkg.id_or_slug, manager.db)
    if pkg:
        rows = [('origin', pkg.origin),
                ('slug', pkg.slug),
                ('name', click.style(pkg.name, bold=True)),
                ('id', pkg.id),
                ('description', fill(pkg.description, max_lines=5)),
                ('homepage', click.style(pkg.url, underline=True)),
                ('version', pkg.version),
                ('release date', pkg.date_published),
                ('folders',
                 '\n'.join([str(pkg.folders[0].path.parent)] +
                           [' ├─ ' + f.path.name for f in pkg.folders[:-1]] +
                           [' └─ ' + pkg.folders[-1].path.name])),
                ('strategy', pkg.options.strategy),]
        print(_tabulate(rows, show_index=False))
    else:
        print(MESSAGES[Manager.PkgNotInstalled](addon[0]))


@main.command()
@click.argument('addon', callback=_decompose_addon_defn)
@click.pass_obj
def hearth(manager, addon):
    """Open the add-on's homepage in your browser."""
    pkg = addon[1]
    pkg = Pkg.unique(pkg.origin, pkg.id_or_slug, manager.db)
    if pkg:
        webbrowser.open(pkg.url)
    else:
        print(MESSAGES[Manager.PkgNotInstalled](addon[0]))


@main.command()
@click.argument('addon', callback=_decompose_addon_defn)
@click.pass_obj
def reveal(manager, addon):
    """Open the add-on folder in your file manager."""
    pkg = addon[1]
    pkg = Pkg.unique(pkg.origin, pkg.id_or_slug, manager.db)
    if pkg:
        webbrowser.open(pkg.folders[0].path.as_uri())
    else:
        print(MESSAGES[Manager.PkgNotInstalled](addon[0]))


@main.group()
def debug():
    """Debugging funcionality."""


@debug.command(name='shell')
@click.pass_context
def shell(ctx):
    """Drop into an interactive shell.

    The shell is created in context and provides access to the
    currently-active manager.
    """
    try:
        from IPython import embed
    except ImportError:
        print('ipython is not installed')
    else:
        embed()


@debug.group()
def cache():
    """Manage the resolver cache."""


@cache.command()
@click.pass_obj
def invalidate(manager):
    """Invalidate the cache.  This sets the date retrieved for every
    cache entry to 1970 to trigger a recheck on the next run.
    """
    from datetime import datetime
    from .models import CacheEntry
    manager.db.query(CacheEntry).update({'date_retrieved': datetime.fromtimestamp(0)})
    manager.db.commit()


@cache.command()
@click.pass_obj
def clear(manager):
    """Nuke the cache from orbit."""
    from .models import CacheEntry
    manager.db.query(CacheEntry).delete()
    manager.db.commit()


@main.group()
def extras():
    pass


@extras.group()
def bitbar():
    """Mini update GUI implemented as a BitBar plug-in.

    BitBar <https://getbitbar.com/> is a menu-bar app host for macOS.
    """


@bitbar.command(help='[internal]')
@click.argument('caller')
@click.argument('version')
@click.pass_obj
def _generate(manager, caller, version):
    from base64 import b64encode
    from pathlib import Path

    outdated = manager.db.query(Pkg).order_by(Pkg.name).all()
    outdated = zip(outdated,
                   manager.resolve_many((p.origin, p.id, p.options.strategy)
                                        for p in outdated))
    outdated = [(p, r) for p, r in outdated
                if p.file_id != getattr(r, 'file_id', p.file_id)]

    icon = Path(__file__).parent/'assets'/\
           f'NSStatusItem-icon__{"has-updates" if outdated else "clear"}.png'
    icon = b64encode(icon.read_bytes()).decode()

    print(f'| templateImage="{icon}"\n---')
    if outdated:
        if len(outdated) > 1:
            print(f'''\
Update all | bash={caller} param1=update terminal=false refresh=true''')
        for p, r in outdated:
            print(f'''\
Update {r.name} ({p.version} ➞ {r.version}) | \
  bash={caller} param1=update param2={_compose_addon_defn(r)} \
  terminal=false refresh=true''')
    else:
        print('No add-on updates available')


@bitbar.command()
def install():
    """Install the instawow BitBar plug-in."""
    from pathlib import Path
    import tempfile
    import sys

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
