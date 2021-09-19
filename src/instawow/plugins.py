# pyright: reportUnknownVariableType=false
# pyright: reportUntypedFunctionDecorator=false

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import Any

import click
import pluggy

from . import resolvers

_project_name = __package__

hookspec = pluggy.HookspecMarker(_project_name)
hookimpl = pluggy.HookimplMarker(_project_name)


class InstawowPlugin:
    "The plug-in interface."

    @hookspec
    def instawow_add_commands(self) -> Iterable[click.Command]:
        "Additional commands to register with ``click``."

    @hookspec
    def instawow_add_resolvers(self) -> Iterable[resolvers.Resolver]:
        "Additional resolvers to load."


@lru_cache(maxsize=None)
def load_plugins() -> Any:
    plugin_manager = pluggy.PluginManager(_project_name)
    plugin_manager.add_hookspecs(InstawowPlugin)
    plugin_manager.load_setuptools_entrypoints(f'{_project_name}.plugins')
    return plugin_manager.hook
