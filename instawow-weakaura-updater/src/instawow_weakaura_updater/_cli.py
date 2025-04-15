from __future__ import annotations

import click

from instawow import config_ctx
from instawow.cli import run_with_progress
from instawow.cli._helpers import ManyOptionalChoiceValueParam


@click.group('weakauras-companion')
def weakaura_updater_command_group() -> None:
    "Manage your WeakAuras."


@weakaura_updater_command_group.command('build')
def build_weakauras_companion() -> None:
    "Build the WeakAuras Companion add-on."

    from .builder import build_addon
    from .config import PluginConfig

    plugin_config = PluginConfig.read(config_ctx.config()).ensure_dirs()
    run_with_progress(build_addon(plugin_config))


@weakaura_updater_command_group.command
@click.argument(
    'collapsed-editable-config-values',
    nargs=-1,
    type=ManyOptionalChoiceValueParam(click.Choice(('access_tokens.wago',))),
)
def configure(collapsed_editable_config_values: dict[str, object]) -> None:
    "Configure the plug-in."

    from instawow.cli.prompts import password

    from .config import PluginConfig

    wago_access_token = collapsed_editable_config_values.get('access_tokens.wago')
    if wago_access_token is None:
        wago_access_token = password('Wago access token:').prompt()
    if not wago_access_token:  # Convert to ``None`` if empty string.
        wago_access_token = None

    plugin_config = PluginConfig.from_values(
        {'access_tokens': {'wago': wago_access_token}, 'profile_config': config_ctx.config()}
    ).write()

    click.echo('Configuration written to:')
    click.echo(f'  {plugin_config.config_file_path}')


@weakaura_updater_command_group.command('list')
def list_installed_wago_auras() -> None:
    "List WeakAuras installed from Wago."

    from instawow._utils.text import tabulate

    from .builder import extract_installed_auras
    from .config import PluginConfig

    plugin_config = PluginConfig.read(config_ctx.config()).ensure_dirs()

    installed_auras = sorted(
        (account, addon.name, a.id, a.url.parent)
        for account, addon, auras in extract_installed_auras(plugin_config)
        for v in auras.values()
        for a in v
        if not a.parent
    )
    click.echo(tabulate([('account', 'add-on', 'aura name', 'aura URL'), *installed_auras]))
