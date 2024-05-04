from __future__ import annotations

from pathlib import Path

from instawow._utils.compat import fauxfrozen
from instawow.config import PluginConfig as _PluginConfig


@fauxfrozen
class PluginConfig(_PluginConfig):
    @property
    def access_token(self) -> str | None:
        return self.profile_config.global_config.access_tokens.wago

    @property
    def addon_zip_file(self) -> Path:
        return self.profile_cache_dir / 'WeakAurasCompanion.zip'

    @property
    def changelog_file(self) -> Path:
        return self.profile_cache_dir / 'CHANGELOG.md'

    @property
    def version_file(self) -> Path:
        return self.profile_cache_dir / 'version.txt'
