
from collections import namedtuple
from functools import partial
from textwrap import fill
import webbrowser

import click
from sqlalchemy import inspect
from tabulate import tabulate

from . import __version__
from .config import UserConfig
from .constants import MESSAGES
from .manager import run
from .models import Pkg
from .utils import TocReader, format_columns


_CONTEXT_SETTINGS = {'help_option_names': ['-h', '--help']}

_tabulate = partial(tabulate, showindex=True, tablefmt='fancy_grid')


def _compose_addon_defn(pkg):
    return ':'.join((pkg.origin, pkg.slug))


_parts = namedtuple('Parts', 'origin id_or_slug')


def _decompose_addon_defn(ctx, param, value):
    if isinstance(value, tuple):
        return [_decompose_addon_defn(ctx, param, v) for v in value]
    for resolver in ctx.obj.resolvers.values():
        parts = resolver.decompose_url(value)
        if parts:
            parts = _parts(*parts)
            break
    else:
        if ':' not in value:
            raise click.BadParameter(value)
        parts = value.partition(':')
        parts = _parts(parts[0], parts[-1])
    return value, parts


def cli():
    while True:
        try:
            config = UserConfig.read()
        except (FileNotFoundError, ValueError):
            _init()
        else:
            break
    with run(config) as manager:
        main(obj=manager)


def _init():
    addon_dir = UserConfig.default_addon_dir
    while True:
        try:
            UserConfig(addon_dir=addon_dir).mk_app_dirs().write()
        except ValueError:
            if addon_dir:
                click.echo(f'{addon_dir!r} not found')
            addon_dir = click.prompt('Please enter the path to your add-on folder')
        else:
            break

init = click.Command(name='instawow-init', callback=_init,
                     context_settings=_CONTEXT_SETTINGS)


@click.group(context_settings=_CONTEXT_SETTINGS)
@click.version_option(__version__)
def main():
    """Add-on manager for World of Warcraft."""


@main.command()
@click.argument('addons', nargs=-1, callback=_decompose_addon_defn)
@click.option('--strategy', '-s',
              type=click.Choice(['canonical', 'latest']),
              default='canonical',
              help="Whether to install the latest published version "
                   "('canonical') or the very latest upload ('latest').")
@click.option('--overwrite', '-o',
              is_flag=True, default=False,
              help='Whether to overwrite existing add-ons.')
@click.pass_obj
def install(manager, addons, overwrite, strategy):
    """Install add-ons."""
    for addon, result in \
            zip((d for d, _ in addons),
                manager.run(manager.install_many((*p, strategy, overwrite)
                                                 for _, p in addons))):
        try:
            if isinstance(result, Exception):
                raise result
        except manager.PkgAlreadyInstalled:
            click.echo(MESSAGES['install_failure__installed'](id=addon))
        except manager.PkgOriginInvalid:
            click.echo(MESSAGES['install_failure__invalid_origin'](id=addon))
        except manager.PkgNonexistent:
            click.echo(MESSAGES['any_failure__non_existent'](id=addon))
        except manager.PkgConflictsWithPreexisting:
            click.echo(MESSAGES['install_failure__preexisting_'
                                'folder_conflict'](id=addon))
        except manager.PkgConflictsWithInstalled as e:
            click.echo(MESSAGES['any_failure__installed_folder_conflict'](
                id=addon, other=_compose_addon_defn(e.conflicting_pkg)))
        else:
            click.echo(MESSAGES['install_success'](id=addon, version=result.version))


@main.command()
@click.argument('addons', nargs=-1, callback=_decompose_addon_defn)
@click.pass_obj
def update(manager, addons):
    """Update installed add-ons."""
    if not addons:
        addons = [(_compose_addon_defn(p), (p.origin, p.id))
                  for p in manager.db.query(Pkg).order_by(Pkg.slug).all()]
    for addon, result in \
            zip((d for d, _ in addons),
                manager.run(manager.update_many(p for _, p in addons))):
        try:
            if isinstance(result, Exception):
                raise result
        except manager.PkgNonexistent:
            click.echo(MESSAGES['any_failure__non_existent'](id=addon))
        except manager.PkgNotInstalled:
            click.echo(MESSAGES['any_failure__not_installed'](id=addon))
        except manager.PkgConflictsWithInstalled as e:
            click.echo(MESSAGES['any_failure__installed_folder_conflict'](
                id=addon, other=_compose_addon_defn(e.conflicting_pkg)))
        except manager.PkgUpToDate:
            pass
        else:
            click.echo(MESSAGES['update_success'](id=addon,
                                                  old_version=result[0].version,
                                                  new_version=result[1].version))


@main.command()
@click.argument('addons', nargs=-1, callback=_decompose_addon_defn)
@click.pass_obj
def remove(manager, addons):
    """Uninstall add-ons."""
    for addon, parts in addons:
        try:
            manager.remove(*parts)
        except manager.PkgNotInstalled:
            click.echo(MESSAGES['any_failure__not_installed'](id=addon))
        else:
            click.echo(MESSAGES['remove_success'](id=addon))


@main.group('list')
@click.pass_obj
def list_(manager):
    """List add-ons."""


@list_.command()
@click.option('--column', '-c',
              multiple=True,
              help='A field to show in a column.  Nested fields are '
                   'dot-delimited.  Can be repeated.')
@click.option('--columns', '-C',
              is_flag=True, default=False,
              help='Whether to print a list of all possible column values.')
@click.pass_obj
def installed(manager, column, columns):
    """List installed add-ons."""
    if columns:
        # TODO: include relationships in output
        click.echo(_tabulate(([c] for c in inspect(Pkg).columns.keys()),
                             headers=['field']))
    else:
        pkgs = manager.db.query(Pkg).order_by(Pkg.slug).all()
        if not pkgs:
            return
        try:
            click.echo(_tabulate(([_compose_addon_defn(p),
                                   *format_columns(p, column)] for p in pkgs),
                                 headers=['add-on', *column]))
        except AttributeError as e:
            raise click.BadParameter(e.args)


@list_.command()
@click.pass_obj
def outdated(manager):
    """List outdated add-ons."""
    old = manager.db.query(Pkg).order_by(Pkg.slug).all()
    new = manager.run(manager.resolve_many((p.origin, p.id, p.options.strategy)
                                           for p in old))
    outdated = [(p, r) for p, r in zip(old, new)
                if not isinstance(r, Exception) and p.file_id != str(r.file_id)]
    if outdated:
        click.echo(_tabulate(([_compose_addon_defn(r),
                               p.version, r.version, r.options.strategy]
                              for p, r in outdated),
                             headers=['add-on', 'current version',
                                      'new version', 'strategy']))


@list_.command()
@click.pass_obj
def preexisting(manager):
    """List add-ons not installed by instawow."""
    folders = sorted({f.name
                      for f in manager.config.addon_dir.iterdir() if f.is_dir()}
                     - {f.path.name
                        for p in manager.db.query(Pkg).all() for f in p.folders})
    if folders:
        folders = ((a, TocReader(manager.config.addon_dir/a/f'{a}.toc'))
                   for a in folders)
        click.echo(_tabulate(([a, t['X-Curse-Project-ID'].value,
                               t['X-Curse-Packaged-Version', 'X-Packaged-Version',
                                 'Version'].value] for a, t in folders),
                             headers=['folder', 'curse id or slug', 'version']))


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
            click.echo(MESSAGES['set_success'](id=addon[0], var='strategy',
                                               new_strategy=strategy))
        else:
            click.echo(MESSAGES['any_failure__not_installed'](id=addon[0]))


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
                ('description', fill(pkg.description)),
                ('homepage', click.style(pkg.url, underline=True)),
                ('version', pkg.version),
                ('release date', pkg.date_published),
                ('folders',
                 '\n'.join([str(pkg.folders[0].path.parent)] +
                           [' ├─ ' + f.path.name for f in pkg.folders[:-1]] +
                           [' └─ ' + pkg.folders[-1].path.name])),
                ('strategy', pkg.options.strategy),]
        click.echo(_tabulate(rows, showindex=False))
    else:
        click.echo(MESSAGES['any_failure__not_installed'](id=addon[0]))


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
        click.echo(MESSAGES['any_failure__not_installed'](id=addon[0]))


@main.command()
@click.argument('addon', callback=_decompose_addon_defn)
@click.pass_obj
def reveal(manager, addon):
    """Open the add-on folder in your file manager."""
    pkg = addon[1]
    pkg = Pkg.unique(pkg.origin, pkg.id_or_slug, manager.db)
    if pkg:
        webbrowser.open(f'file://{pkg.folders[0].path}')
    else:
        click.echo(MESSAGES['any_failure__not_installed'](id=addon[0]))
