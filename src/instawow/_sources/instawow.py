from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from .. import config_ctx
from .._utils.aio import run_in_thread
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..resolvers import BaseResolver, CatalogueEntryCandidate, PkgCandidate
from ..results import PkgNonexistent
from ..wow_installations import Flavour


class _ResolveMetadata(TypedDict):
    requires_build: bool


_ADDONS = {
    ('0', 'weakauras-companion'): _ResolveMetadata(requires_build=False),
    ('1', 'weakauras-companion-autoupdate'): _ResolveMetadata(requires_build=True),
}


class InstawowResolver(BaseResolver):
    metadata = SourceMetadata(
        id='instawow',
        name='instawow',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Markdown,
        addon_toc_key=None,
    )

    async def resolve_one(self, defn: Defn, metadata: None):
        from instawow_wa_updater._config import PluginConfig
        from instawow_wa_updater._core import WaCompanionBuilder

        try:
            (id_, slug), metadata_ = next((p, v) for p, v in _ADDONS.items() if defn.alias in p)
        except StopIteration:
            raise PkgNonexistent from None

        builder_config = PluginConfig(profile_config=config_ctx.config())
        builder = WaCompanionBuilder(builder_config)
        if metadata_['requires_build']:
            await run_in_thread(builder_config.ensure_dirs)()
            await builder.build()

        return PkgCandidate(
            id=id_,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.build_paths.archive.as_uri(),
            date_published=datetime.now(UTC),
            version=await run_in_thread(builder.build_paths.version.read_text)(encoding='utf-8'),
            changelog_url=builder.build_paths.changelog.as_uri(),
        )

    async def catalogue(self):
        yield CatalogueEntryCandidate(
            id='1',
            slug='weakauras-companion-autoupdate',
            name='WeakAuras Companion',
            url='https://github.com/layday/instawow',
            game_flavours=frozenset(Flavour),
            download_count=1,
            last_updated=datetime.now(UTC),
            folders=[
                frozenset({'WeakAurasCompanion'}),
            ],
        )
