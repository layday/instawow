from __future__ import annotations

import instawow.plugins

from ._cli import wa_updater_command_group


@instawow.plugins.hookimpl
def instawow_add_commands():
    return (wa_updater_command_group,)
