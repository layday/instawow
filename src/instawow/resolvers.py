from __future__ import annotations

import enum
import urllib.parse
from collections.abc import AsyncIterator, Collection, Iterable, Sequence
from functools import update_wrapper
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypeVar

from typing_extensions import Self
from yarl import URL

from . import archives, http, manager_ctx, pkg_models
from . import results as R
from .catalogue.cataloguer import CatalogueEntry
from .common import AddonHashMethod, Defn, SourceMetadata
from .config import GlobalConfig
from .utils import file_uri_to_path, gather, run_in_thread


class FolderHashCandidate(Protocol):  # pragma: no cover
    @property
    def name(self) -> str:
        ...

    def hash_contents(self, __method: AddonHashMethod) -> str:
        ...


TFolderHashCandidate = TypeVar('TFolderHashCandidate', bound=FolderHashCandidate)


class HeadersIntent(enum.IntEnum):
    Download = enum.auto()


class Resolver(Protocol):  # pragma: no cover
    metadata: ClassVar[SourceMetadata]
    'Static source metadata.'

    requires_access_token: ClassVar[str | None]
    'Access token key or ``None``.'

    archive_opener: ClassVar[archives.ArchiveOpener | None]
    'Alternative archive opener to use supporting e.g. non-standard archive formats or layouts.'

    def __init__(self, manager_ctx: manager_ctx.ManagerCtx) -> None:
        ...

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


class BaseResolver(Resolver, Protocol):
    _manager_ctx: manager_ctx.ManagerCtx

    archive_opener = None

    def __init__(self, manager_ctx: manager_ctx.ManagerCtx) -> None:
        self._manager_ctx = manager_ctx

    __orig_init = __init__

    def __init_subclass__(cls) -> None:
        # ``Protocol`` clobbers ``__init__`` in Python < 3.11.  The fix was
        # also backported to 3.9 and 3.10 at some point.
        if cls.__init__ is _DummyResolver.__init__:
            cls.__init__ = cls.__orig_init

        if cls.resolve_one is not super().resolve_one:

            async def resolve_one(self: Self, defn: Defn, metadata: Any) -> pkg_models.Pkg:
                extraneous_strategies = (
                    defn.strategies.filled_strategies.keys() - self.metadata.strategies
                )
                if extraneous_strategies:
                    raise R.PkgStrategiesUnsupported(extraneous_strategies)
                return await cls_resolve_one(self, defn, metadata)

            cls_resolve_one = cls.resolve_one
            setattr(cls, cls.resolve_one.__name__, update_wrapper(resolve_one, cls.resolve_one))

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
        results = await gather((self.resolve_one(d, None) for d in defns), R.resultify_async_exc)
        return dict(zip(defns, results))

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
