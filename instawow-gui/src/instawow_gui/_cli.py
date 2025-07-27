from __future__ import annotations

import click

from instawow import _version

from . import NAME


@click.command
@click.option('--app-name', default=NAME, help='GUI app name.')
def gui(app_name: str) -> None:
    from ._app import make_app

    make_app(app_name=app_name, version=_version.get_version()).main_loop()
