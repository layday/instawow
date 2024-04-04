from __future__ import annotations

import click

import instawow.plugins


@click.command('gui')
@click.pass_context
def _gui_command(ctx: click.Context) -> None:
    "Fire up the GUI."
    from instawow import __version__
    from instawow._logging import setup_logging
    from instawow.config import GlobalConfig, ProfileConfig

    from .app import InstawowApp

    global_config = GlobalConfig.read().ensure_dirs()
    dummy_jsonrpc_config = ProfileConfig.make_dummy_config(
        global_config=global_config, profile='__jsonrpc__'
    ).ensure_dirs()

    params = ctx.find_root().params
    setup_logging(dummy_jsonrpc_config.logging_dir, *params['verbose'])

    InstawowApp(debug=any(params['verbose']), version=__version__).main_loop()


@instawow.plugins.hookimpl
def instawow_add_commands():
    return (_gui_command,)
