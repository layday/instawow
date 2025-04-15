from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict

from .. import config_ctx, sync_ctx
from .._utils.aio import run_in_thread
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..resolvers import BaseResolver, CatalogueEntryCandidate, PkgCandidate
from ..results import PkgNonexistent
from ..wow_installations import Flavour

_READ_PLUGIN_CONFIG_LOCK = (object(), '_READ_PLUGIN_CONFIG_')


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

    __plugin_config = None

    async def resolve_one(self, defn: Defn, metadata: None):
        from instawow_weakaura_updater import builder
        from instawow_weakaura_updater.config import PluginConfig

        try:
            (id_, slug), metadata_ = next((p, v) for p, v in _ADDONS.items() if defn.alias in p)
        except StopIteration:
            raise PkgNonexistent from None

        async with sync_ctx.locks()[_READ_PLUGIN_CONFIG_LOCK]:
            plugin_config = self.__plugin_config
            if plugin_config is None:
                plugin_config = self.__plugin_config = await run_in_thread(PluginConfig.read)(
                    config_ctx.config()
                )

        build_paths = (
            await builder.build_addon(plugin_config)
            if metadata_['requires_build']
            else builder.get_build_paths(plugin_config)
        )

        return PkgCandidate(
            id=id_,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=build_paths.archive.as_uri(),
            date_published=datetime.now(UTC),
            version=await run_in_thread(build_paths.version.read_text)(encoding='utf-8'),
            changelog_url=build_paths.changelog.as_uri(),
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
