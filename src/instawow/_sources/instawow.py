from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from .. import results as R
from .._utils.aio import run_in_thread
from ..catalogue.cataloguer import CatalogueEntry
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..http import ClientSessionType
from ..resolvers import BaseResolver, PkgCandidate
from ..wow_installations import Flavour

_ADDONS = {
    ('0', 'weakauras-companion'),
    ('1', 'weakauras-companion-autoupdate'),
}


class InstawowResolver(BaseResolver):
    metadata = SourceMetadata(
        id='instawow',
        name='instawow',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Markdown,
        addon_toc_key=None,
    )
    requires_access_token = None

    async def _resolve_one(self, defn: Defn, metadata: None) -> PkgCandidate:
        try:
            source_id, slug = next(p for p in _ADDONS if defn.alias in p)
        except StopIteration:
            raise R.PkgNonexistent from None

        from instawow_wa_updater._core import WaCompanionBuilder

        builder = WaCompanionBuilder(self._manager_ctx)
        if source_id == '1':
            await builder.build()

        return PkgCandidate(
            id=source_id,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.addon_zip_path.as_uri(),
            date_published=datetime.now(timezone.utc),
            version=await run_in_thread(builder.get_version)(),
            changelog_url=builder.changelog_path.as_uri(),
        )

    @classmethod
    async def catalogue(cls, web_client: ClientSessionType) -> AsyncIterator[CatalogueEntry]:
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
