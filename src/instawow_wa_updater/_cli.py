from __future__ import annotations

import click

from instawow import cli


@click.group('weakauras-companion')
def wa_updater_command_group() -> None:
    "Manage your WeakAuras."


@wa_updater_command_group.command('build')
@click.pass_obj
def build_weakauras_companion(config_ctx: cli.ConfigBoundCtxProxy) -> None:
    "Build the WeakAuras Companion add-on."

    from ._core import WaCompanionBuilder

    cli.run_with_progress(WaCompanionBuilder(config_ctx.config).build())


@wa_updater_command_group.command('list')
@click.pass_obj
def list_installed_wago_auras(config_ctx: cli.ConfigBoundCtxProxy) -> None:
    "List WeakAuras installed from Wago."
    from instawow._utils.text import tabulate

    from ._core import WaCompanionBuilder

    builder = WaCompanionBuilder(config_ctx.config)
    builder.config.ensure_dirs()

    installed_auras = sorted(
        (g.addon_name, a.id, a.url)
        for g in builder.extract_installed_auras()
        for v in g.root.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('type', 'name', 'URL'), *installed_auras]))
