from __future__ import annotations

import instawow.plugins

from ._cli import gui as gui_command


@instawow.plugins.hook
def instawow_add_commands():
    return (gui_command,)
