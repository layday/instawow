from __future__ import annotations

import datetime as dt
import enum
import urllib.parse
from collections.abc import AsyncIterator, Collection, Sequence
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypedDict, TypeVar

from typing_extensions import NotRequired, deprecated
from yarl import URL

from . import config as _config
from . import pkg_archives, pkg_models
from . import results as R
from .catalogue import cataloguer
from .definitions import Defn, SourceMetadata


class FolderHashCandidate(Protocol):  # pragma: no cover
    @property
    def name(self) -> str: ...
    @property
    def path(self) -> Path: ...


TFolderHashCandidate = TypeVar('TFolderHashCandidate', bound=FolderHashCandidate)


class HeadersIntent(enum.IntEnum):
    Download = enum.auto()


class Resolver(Protocol):  # pragma: no cover
    metadata: ClassVar[SourceMetadata]
    'Static source metadata.'

    requires_access_token: ClassVar[str | None]
    'Access token key or ``None``.'

    archive_opener: ClassVar[pkg_archives.ArchiveOpener | None]
    'Alternative archive opener to use supporting e.g. non-standard archive formats or layouts.'

    def __init__(self, config: _config.ProfileConfig) -> None: ...

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        "Attempt to extract a ``Defn`` alias from a given URL."
        ...

    async def make_request_headers(
        self, intent: HeadersIntent | None = None
    ) -> dict[str, str] | None:
        "Create headers for resolver HTTP requests."
        ...

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, pkg_models.Pkg | R.ManagerError | R.InternalError]:
        "Resolve multiple ``Defn``s into packages."
        ...

    async def resolve_one(self, defn: Defn, metadata: Any) -> pkg_models.Pkg:
        "Resolve a ``Defn`` into a package."
        ...

    async def get_changelog(self, uri: URL) -> str:
        "Retrieve a changelog from a URI."
        ...

    async def get_folder_hash_matches(
        self, candidates: Collection[TFolderHashCandidate]
    ) -> list[tuple[Defn, frozenset[TFolderHashCandidate]]]:
        "Find ``Defn``s from folder fingerprint."
        ...

    @classmethod
    def catalogue(cls) -> AsyncIterator[cataloguer.CatalogueEntry]:
        "Enumerate add-ons from the source."
        ...


class PkgCandidate(TypedDict):
    "A subset of the ``Pkg`` constructor's kwargs."

    id: str
    slug: str
    name: str
    description: str
    url: str
    download_url: str
    date_published: dt.datetime
    version: str
    changelog_url: str
    deps: NotRequired[list[pkg_models.PkgDep]]


class BaseResolver(Resolver, Protocol):
    archive_opener = None

    _config: _config.ProfileConfig

    def __init__(self, config: _config.ProfileConfig) -> None:
        self._config = config

    __orig_init = __init__

    def __init_subclass__(cls) -> None:
        # ``Protocol`` clobbers ``__init__`` on Python < 3.11.
        if cls.__init__ is _DummyResolver.__init__:
            cls.__init__ = cls.__orig_init

    @property
    @deprecated(
        'Use ``self._config.game_flavour`` and ``instawow.shared_ctx.web_client`` instead.'
    )
    def _config_ctx(self) -> Any:
        from types import SimpleNamespace

        from . import shared_ctx

        return SimpleNamespace(
            config=self._config,
            web_client=property(shared_ctx.web_client_var.get),
        )

    @classmethod
    def _get_access_token(
        cls, global_config: _config.GlobalConfig, name: str | None = None
    ) -> str | None:
        name = name or cls.requires_access_token
        if name is not None:
            return getattr(global_config.access_tokens, name, None)

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        return None

    async def make_request_headers(
        self, intent: HeadersIntent | None = None
    ) -> dict[str, str] | None:
        return None

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, pkg_models.Pkg | R.ManagerError | R.InternalError]:
        from ._progress_reporting import make_incrementing_progress_tracker
        from ._utils.aio import gather

        track_progress = make_incrementing_progress_tracker(
            len(defns), f'Resolving add-ons: {self.metadata.name}'
        )
        results = await gather(
            track_progress(R.resultify_async_exc(self.resolve_one(d, None))) for d in defns
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: Any) -> pkg_models.Pkg:
        extraneous_strategies = defn.strategies.filled.keys() - self.metadata.strategies
        if extraneous_strategies:
            raise R.PkgStrategiesUnsupported(extraneous_strategies)

        pkg_candidate = await self._resolve_one(defn, metadata)
        return pkg_models.Pkg(
            **pkg_candidate,
            source=self.metadata.id,
            options=pkg_models.PkgOptions(**{k: bool(v) for k, v in defn.strategies.items()}),
        )

    async def _resolve_one(self, defn: Defn, metadata: Any) -> PkgCandidate:
        "Resolve a ``Defn`` into a package."
        ...

    async def get_changelog(self, uri: URL) -> str:
        from . import http, shared_ctx
        from ._utils.aio import run_in_thread
        from ._utils.web import file_uri_to_path

        match uri.scheme:
            case 'data' if uri.raw_path.startswith(','):
                return urllib.parse.unquote(uri.raw_path[1:])

            case 'file':
                return await run_in_thread(Path(file_uri_to_path(str(uri))).read_text)(
                    encoding='utf-8'
                )

            case 'http' | 'https':
                async with shared_ctx.web_client.get(
                    uri,
                    expire_after=http.CACHE_INDEFINITELY,
                    headers=await self.make_request_headers(),
                    raise_for_status=True,
                ) as response:
                    return await response.text()

            case _:
                raise ValueError('Unsupported URI with scheme', uri.scheme)

    async def get_folder_hash_matches(
        self, candidates: Collection[TFolderHashCandidate]
    ) -> list[tuple[Defn, frozenset[TFolderHashCandidate]]]:
        return []

    @classmethod
    async def catalogue(cls) -> AsyncIterator[cataloguer.CatalogueEntry]:
        return
        yield


class _DummyResolver(Resolver):
    pass


class Resolvers(dict[str, Resolver]):
    @cached_property
    def archive_opener_dict(self) -> _ResolverArchiveOpenerDict:
        return _ResolverArchiveOpenerDict(self)

    @cached_property
    def priority_dict(self) -> _ResolverPriorityDict:
        return _ResolverPriorityDict(self)

    @cached_property
    def addon_toc_key_and_id_pairs(self) -> Collection[tuple[str, str]]:
        return [
            (r.metadata.addon_toc_key, r.metadata.id)
            for r in self.values()
            if r.metadata.addon_toc_key
        ]


class _ResolverArchiveOpenerDict(dict[str, pkg_archives.ArchiveOpener]):
    def __init__(self, resolvers: Resolvers) -> None:
        super().__init__(
            (r.metadata.id, r.archive_opener) for r in resolvers.values() if r.archive_opener
        )

    def __missing__(self, key: str) -> pkg_archives.ArchiveOpener:
        return pkg_archives.open_zip_archive


class _ResolverPriorityDict(dict[str, float]):
    def __init__(self, resolvers: Resolvers) -> None:
        super().__init__((n, i) for i, n in enumerate(resolvers))

    def __missing__(self, key: str) -> float:
        return float('inf')
