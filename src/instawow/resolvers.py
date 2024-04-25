from __future__ import annotations

import datetime as dt
import enum
import urllib.parse
from collections.abc import AsyncIterator, Collection, Iterable, Sequence
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypedDict, TypeVar

import attrs
from typing_extensions import NotRequired
from yarl import URL

from . import http, manager_ctx, matchers, pkg_archives, pkg_models
from . import results as R
from ._utils.aio import gather, run_in_thread
from ._utils.web import file_uri_to_path
from .catalogue.cataloguer import CatalogueEntry
from .config import GlobalConfig
from .definitions import Defn, SourceMetadata


class FolderHashCandidate(Protocol):  # pragma: no cover
    @property
    def name(self) -> str: ...

    def hash_contents(self, __method: matchers.AddonHashMethod) -> str: ...


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

    def __init__(self, manager_ctx: manager_ctx.ManagerCtx) -> None: ...

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
    ) -> Iterable[tuple[Defn, frozenset[TFolderHashCandidate]]]:
        "Find ``Defn``s from folder fingerprint."
        ...

    @classmethod
    def catalogue(cls, web_client: http.ClientSessionType) -> AsyncIterator[CatalogueEntry]:
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
    _manager_ctx: manager_ctx.ManagerCtx

    archive_opener = None

    def __init__(self, manager_ctx: manager_ctx.ManagerCtx) -> None:
        self._manager_ctx = manager_ctx

    __orig_init = __init__

    def __init_subclass__(cls) -> None:
        # ``Protocol`` clobbers ``__init__`` on Python < 3.11.
        if cls.__init__ is _DummyResolver.__init__:
            cls.__init__ = cls.__orig_init

    @classmethod
    def _get_access_token(cls, global_config: GlobalConfig, name: str | None = None) -> str | None:
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
        results = await gather(R.resultify_async_exc(self.resolve_one(d, None)) for d in defns)
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: Any) -> pkg_models.Pkg:
        extraneous_strategies = defn.strategies.filled_strategies.keys() - self.metadata.strategies
        if extraneous_strategies:
            raise R.PkgStrategiesUnsupported(extraneous_strategies)

        pkg_candidate = await self._resolve_one(defn, metadata)
        return pkg_models.Pkg(
            **pkg_candidate,
            source=self.metadata.id,
            options=pkg_models.PkgOptions(
                **attrs.asdict(defn.strategies, value_serializer=lambda t, a, v: bool(v))
            ),
        )

    async def _resolve_one(self, defn: Defn, metadata: Any) -> PkgCandidate:
        "Resolve a ``Defn`` into a package."
        ...

    async def get_changelog(self, uri: URL) -> str:
        match uri.scheme:
            case 'data' if uri.raw_path.startswith(','):
                return urllib.parse.unquote(uri.raw_path[1:])

            case 'file':
                return await run_in_thread(Path(file_uri_to_path(str(uri))).read_text)(
                    encoding='utf-8'
                )

            case 'http' | 'https':
                async with self._manager_ctx.web_client.get(
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
    ) -> Iterable[tuple[Defn, frozenset[TFolderHashCandidate]]]:
        return []

    @classmethod
    async def catalogue(cls, web_client: http.ClientSessionType) -> AsyncIterator[CatalogueEntry]:
        return
        yield


class _DummyResolver(Resolver):
    pass
