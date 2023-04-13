from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from .. import models
from .. import results as R
from ..cataloguer import BaseCatalogueEntry
from ..common import ChangelogFormat, Defn, Flavour, SourceMetadata
from ..http import ClientSessionType
from ..resolvers import BaseResolver
from ..utils import run_in_thread


class InstawowResolver(BaseResolver):
    metadata = SourceMetadata(
        id='instawow',
        name='instawow',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.markdown,
        addon_toc_key=None,
    )
    requires_access_token = None

    _ADDONS = {
        ('0', 'weakauras-companion'),
        ('1', 'weakauras-companion-autoupdate'),
    }

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        try:
            source_id, slug = next(p for p in self._ADDONS if defn.alias in p)
        except StopIteration:
            raise R.PkgNonexistent

        from ..wa_updater import WaCompanionBuilder

        builder = WaCompanionBuilder(self._manager)
        if source_id == '1':
            await builder.build()

        return models.Pkg(
            source=self.metadata.id,
            id=source_id,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.addon_zip_path.as_uri(),
            date_published=datetime.now(timezone.utc),
            version=await run_in_thread(builder.get_version)(),
            changelog_url=builder.changelog_path.as_uri(),
            options=models.PkgOptions.from_strategy_values(defn.strategies),
        )

    @classmethod
    async def catalogue(cls, web_client: ClientSessionType) -> AsyncIterator[BaseCatalogueEntry]:
        yield BaseCatalogueEntry(
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
