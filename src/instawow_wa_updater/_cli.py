from __future__ import annotations

import click

from instawow import cli


@click.group('weakauras-companion')
def wa_updater_command_group() -> None:
    "Manage your WeakAuras."


@wa_updater_command_group.command('build')
@click.pass_obj
def build_weakauras_companion(mw: cli.CtxObjWrapper) -> None:
    "Build the WeakAuras Companion add-on."
    from ._core import WaCompanionBuilder

    mw.run_with_progress(WaCompanionBuilder(mw.manager.ctx).build())


@wa_updater_command_group.command('list')
@click.pass_obj
def list_installed_wago_auras(mw: cli.CtxObjWrapper) -> None:
    "List WeakAuras installed from Wago."
    from instawow._utils.text import tabulate

    from ._core import WaCompanionBuilder

    aura_groups = WaCompanionBuilder(mw.manager.ctx).extract_installed_auras()
    installed_auras = sorted(
        (g.addon_name, a.id, a.url)
        for g in aura_groups
        for v in g.root.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('type', 'name', 'URL'), *installed_auras]))
