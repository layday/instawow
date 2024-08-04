from __future__ import annotations

import click

from instawow import _logging, _version, config


@click.command
@click.pass_context
def gui(ctx: click.Context) -> None:
    "Fire up the GUI."
    from ._app import make_app
    from ._config import PluginConfig

    plugin_config = PluginConfig(
        config.GlobalConfig.read().ensure_dirs(),
    ).ensure_dirs()
    _logging.setup_logging(
        plugin_config.logging_dir,
        *ctx.find_root().params['verbose'],
    )

    make_app(version=_version.get_version()).main_loop()
