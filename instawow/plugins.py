# pyright: reportUntypedFunctionDecorator=false

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from typing import Any

import click
import pluggy

from .resolvers import Resolver

_entrypoint = f'{__package__}.plugins'

hookspec = pluggy.HookspecMarker(__package__)
hookimpl = pluggy.HookimplMarker(__package__)


class InstawowPlugin:
    "The plug-in interface."

    @hookspec
    def instawow_add_commands(self) -> Iterable[click.Command]:
        "Additional commands to register with ``click``."

    @hookspec
    def instawow_add_resolvers(self) -> Iterable[Resolver]:
        "Additional resolvers to load."


@lru_cache(maxsize=None)
def load_plugins() -> Any:
    plugin_manager = pluggy.PluginManager(__package__)
    plugin_manager.add_hookspecs(InstawowPlugin)
    plugin_manager.load_setuptools_entrypoints(_entrypoint)
    return plugin_manager.hook
