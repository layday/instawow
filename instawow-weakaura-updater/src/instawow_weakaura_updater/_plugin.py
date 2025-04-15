from __future__ import annotations

import instawow.plugins

from ._cli import weakaura_updater_command_group


@instawow.plugins.hookimpl
def instawow_add_commands():
    return (weakaura_updater_command_group,)
