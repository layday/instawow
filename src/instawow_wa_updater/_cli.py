from __future__ import annotations

import click

from instawow import config_ctx
from instawow.cli._helpers import ManyOptionalChoiceValueParam


@click.group('weakauras-companion')
def wa_updater_command_group() -> None:
    "Manage your WeakAuras."


@wa_updater_command_group.command('build')
def build_weakauras_companion() -> None:
    "Build the WeakAuras Companion add-on."

    from instawow.cli import run_with_progress

    from ._config import PluginConfig
    from ._core import WaCompanionBuilder

    builder = WaCompanionBuilder(
        PluginConfig.read(config_ctx.config()).ensure_dirs(),
    )
    run_with_progress(builder.build())


@wa_updater_command_group.command
@click.argument(
    'collapsed-editable-config-values',
    nargs=-1,
    type=ManyOptionalChoiceValueParam(click.Choice(('access_tokens.wago',))),
)
def configure(collapsed_editable_config_values: dict[str, object]) -> None:
    "Configure the plug-in."

    from instawow.cli.prompts import password

    from ._config import PluginConfig

    wago_access_token = collapsed_editable_config_values.get('access_tokens.wago')
    if wago_access_token is None:
        wago_access_token = password('Wago access token:').prompt()
    if not wago_access_token:  # Convert to ``None`` if empty string.
        wago_access_token = None

    plugin_config = PluginConfig.from_values(
        {'access_tokens': {'wago': wago_access_token}, 'profile_config': config_ctx.config()}
    ).write()

    click.echo('Configuration written to:')
    click.echo(f'  {plugin_config.config_file}')


@wa_updater_command_group.command('list')
def list_installed_wago_auras() -> None:
    "List WeakAuras installed from Wago."
    from instawow._utils.text import tabulate

    from ._config import PluginConfig
    from ._core import WaCompanionBuilder

    builder = WaCompanionBuilder(
        PluginConfig.read(config_ctx.config()).ensure_dirs(),
    )

    installed_auras = sorted(
        (g.addon_name, a.id, a.url)
        for g in builder.extract_installed_auras()
        for v in g.auras.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('type', 'name', 'URL'), *installed_auras]))
