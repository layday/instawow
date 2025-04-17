from __future__ import annotations

import instawow.plugins

from ._cli import weakaura_updater_command_group


@instawow.plugins.hook
def instawow_add_commands():
    return (weakaura_updater_command_group,)
