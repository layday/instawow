from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from .._utils.aio import run_in_thread
from ..catalogue.cataloguer import CatalogueEntry
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..resolvers import BaseResolver, PkgCandidate
from ..results import PkgNonexistent
from ..wow_installations import Flavour

_ADDONS = {
    ('0', 'weakauras-companion'): False,
    ('1', 'weakauras-companion-autoupdate'): True,
}


class InstawowResolver(BaseResolver):
    metadata = SourceMetadata(
        id='instawow',
        name='instawow',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Markdown,
        addon_toc_key=None,
    )
    access_token = None

    async def _resolve_one(self, defn: Defn, metadata: None) -> PkgCandidate:
        from instawow_wa_updater._config import PluginConfig
        from instawow_wa_updater._core import WaCompanionBuilder

        try:
            (id_, slug), requires_build = next(
                (p, v) for p, v in _ADDONS.items() if defn.alias in p
            )
        except StopIteration:
            raise PkgNonexistent from None

        builder_config = PluginConfig(self._config)
        builder = WaCompanionBuilder(builder_config)
        if requires_build:
            await run_in_thread(builder_config.ensure_dirs)()
            await builder.build()

        return PkgCandidate(
            id=id_,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.build_paths.archive.as_uri(),
            date_published=datetime.now(timezone.utc),
            version=await run_in_thread(builder.build_paths.version.read_text)(encoding='utf-8'),
            changelog_url=builder.build_paths.changelog.as_uri(),
        )

    @classmethod
    async def catalogue(cls) -> AsyncIterator[CatalogueEntry]:
        yield CatalogueEntry(
            source=cls.metadata.id,
            id='1',
            slug='weakauras-companion-autoupdate',
            name='WeakAuras Companion',
            url='https://github.com/layday/instawow',
            game_flavours=frozenset(Flavour),
            download_count=1,
            last_updated=datetime.now(timezone.utc),
            folders=[
                frozenset({'WeakAurasCompanion'}),
            ],
        )
