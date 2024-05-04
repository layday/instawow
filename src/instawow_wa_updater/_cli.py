from __future__ import annotations

import click

from instawow import pkg_management


@click.group('weakauras-companion')
def wa_updater_command_group() -> None:
    "Manage your WeakAuras."


@wa_updater_command_group.command('build')
@click.pass_obj
def build_weakauras_companion(manager: pkg_management.PkgManager) -> None:
    "Build the WeakAuras Companion add-on."
    from instawow.cli import run_with_progress

    from ._core import WaCompanionBuilder

    run_with_progress(WaCompanionBuilder(manager.ctx).build())


@wa_updater_command_group.command('list')
@click.pass_obj
def list_installed_wago_auras(manager: pkg_management.PkgManager) -> None:
    "List WeakAuras installed from Wago."
    from instawow._utils.text import tabulate

    from ._core import WaCompanionBuilder

    builder = WaCompanionBuilder(manager.ctx)
    builder.config.ensure_dirs()

    installed_auras = sorted(
        (g.addon_name, a.id, a.url)
        for g in builder.extract_installed_auras()
        for v in g.root.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('type', 'name', 'URL'), *installed_auras]))
