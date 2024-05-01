from __future__ import annotations

import click

from instawow import cli
from instawow.pkg_management import PkgManager


@click.group('weakauras-companion')
def wa_updater_command_group() -> None:
    "Manage your WeakAuras."


@wa_updater_command_group.command('build')
@click.pass_obj
def build_weakauras_companion(manager: PkgManager) -> None:
    "Build the WeakAuras Companion add-on."
    from ._core import WaCompanionBuilder

    cli.run_with_progress(WaCompanionBuilder(manager.ctx).build())


@wa_updater_command_group.command('list')
@click.pass_obj
def list_installed_wago_auras(manager: PkgManager) -> None:
    "List WeakAuras installed from Wago."
    from instawow._utils.text import tabulate

    from ._core import WaCompanionBuilder

    aura_groups = WaCompanionBuilder(manager.ctx).extract_installed_auras()
    installed_auras = sorted(
        (g.addon_name, a.id, a.url)
        for g in aura_groups
        for v in g.root.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('type', 'name', 'URL'), *installed_auras]))
