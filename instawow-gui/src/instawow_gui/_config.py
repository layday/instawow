from __future__ import annotations

from pathlib import Path

from typing_extensions import Self

from instawow._utils.compat import fauxfrozen
from instawow.config import GlobalConfig
from instawow.config._helpers import ensure_dirs


@fauxfrozen
class PluginConfig:
    global_config: GlobalConfig

    def ensure_dirs(self) -> Self:
        ensure_dirs(
            [
                self.logging_dir,
            ]
        )
        return self

    @property
    def logging_dir(self) -> Path:
        return self.global_config.profiles_state_dir / '__jsonrpc__' / 'logs'
