from __future__ import annotations

import click

from instawow import _version


@click.command
def gui() -> None:
    from ._app import make_app

    make_app(version=_version.get_version()).main_loop()
