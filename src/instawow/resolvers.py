from __future__ import annotations

import datetime as dt
import enum
from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractContextManager
from functools import partial, wraps
from pathlib import Path
from typing import Literal, Never, NotRequired, Protocol, Self, overload

from typing_extensions import TypedDict, TypeVar
from yarl import URL

from . import pkg_archives, wow_installations
from ._utils.attrs import fauxfrozen
from .definitions import Defn, SourceMetadata
from .results import AnyResult, PkgStrategiesUnsupported, resultify

_ResolveMetadataT = TypeVar('_ResolveMetadataT', contravariant=True, default=Never)


class _AccessTokenGetter[R](Protocol):  # pragma: no cover
    def __call__(self) -> tuple[str | None, R]: ...


class AccessTokenMissingError(ValueError):
    def __str__(self) -> str:
        return 'access token missing'


@fauxfrozen
class AccessToken[RequiredT: bool]:
    getter: _AccessTokenGetter[RequiredT]

    @overload
    def get(self: AccessToken[Literal[True]]) -> str: ...
    @overload
    def get(self: AccessToken[bool]) -> str | None: ...
    def get(self) -> str | None:
        access_token, required = self.getter()
        if required and access_token is None:
            raise AccessTokenMissingError
        return access_token


class HeadersIntent(enum.IntEnum):
    Download = enum.auto()


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
    deps: NotRequired[list[_PkgCandidate_Dep]]


class _PkgCandidate_Dep(TypedDict):
    id: str


class CatalogueEntryCandidate(TypedDict):
    "A subset of the ``CatalogueEntry`` constructor's kwargs."

    id: str
    slug: NotRequired[str]
    name: str
    url: str
    game_flavours: frozenset[wow_installations.Flavour]
    download_count: int
    last_updated: dt.datetime
    folders: NotRequired[list[frozenset[str]]]
    same_as: NotRequired[list[_CatalogueEntryCandidate_SameAs]]


class _CatalogueEntryCandidate_SameAs(TypedDict):
    source: str
    id: str


class Resolver(Protocol[_ResolveMetadataT]):  # pragma: no cover
    metadata: SourceMetadata
    'Static source metadata.'

    def get_disabled_reason(self) -> str | None:
        "Reason the resolver might be disabled."
        ...

    async def download_pkg_archive(self, defn: Defn, url: str) -> Path:
        "Package archive downloader."
        ...

    def open_pkg_archive(self, archive_path: Path) -> AbstractContextManager[pkg_archives.Archive]:
        "Package archive opener."
        ...

    def get_alias_from_url(self, url: str) -> str | None:
        "Attempt to extract a ``Defn`` alias from a given URL."
        ...

    def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str] | None:
        "Create headers for resolver HTTP requests."
        ...

    async def resolve(self, defns: Sequence[Defn]) -> dict[Defn, AnyResult[PkgCandidate]]:
        "Resolve multiple ``Defn``s into packages."
        ...

    async def resolve_one(self, defn: Defn, metadata: _ResolveMetadataT | None) -> PkgCandidate:
        "Resolve a ``Defn`` into a package."
        ...

    async def get_changelog(self, url: str) -> str:
        "Retrieve a changelog from a URI."
        ...

    def catalogue(self) -> AsyncIterator[CatalogueEntryCandidate]:
        "Enumerate add-ons from the source."
        ...


class BaseResolver(Resolver[_ResolveMetadataT], Protocol):
    access_token: AccessToken[bool] | None = None
    'Access token retriever.'

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        old_resolve_one = cls.resolve_one
        reassign_resolve_one = partial(setattr, cls, 'resolve_one')

        @reassign_resolve_one
        @wraps(old_resolve_one)
        async def _(self: Self, defn: Defn, metadata: _ResolveMetadataT | None):
            extraneous_strategies = defn.strategies.filled.keys() - self.metadata.strategies
            if extraneous_strategies:
                raise PkgStrategiesUnsupported(extraneous_strategies)

            return await old_resolve_one(self, defn, metadata)

    def get_disabled_reason(self) -> str | None:
        if self.access_token:
            access_token, required = self.access_token.getter()
            if required and access_token is None:
                return str(AccessTokenMissingError())

    async def download_pkg_archive(self, defn: Defn, url: str) -> Path:
        from .pkg_archives._download import download_pkg_archive

        return await download_pkg_archive(defn, url)

    def open_pkg_archive(self, archive_path: Path) -> AbstractContextManager[pkg_archives.Archive]:
        return pkg_archives.open_zip_archive(archive_path)

    def get_alias_from_url(self, url: str) -> str | None:
        return None

    def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str] | None:
        return None

    async def resolve(self, defns: Sequence[Defn]) -> dict[Defn, AnyResult[PkgCandidate]]:
        from ._utils.aio import gather
        from .progress_reporting import make_incrementing_progress_tracker

        track_progress = make_incrementing_progress_tracker(
            len(defns), f'Resolving add-ons: {self.metadata.name}'
        )
        resolve_one = resultify(self.resolve_one)
        results = await gather(track_progress(resolve_one(d, None)) for d in defns)
        return dict(zip(defns, results))

    async def get_changelog(self, url: str) -> str:
        match URL(url):
            case URL(scheme='data') as urly if urly.raw_path.startswith(','):
                import urllib.parse

                return urllib.parse.unquote(urly.raw_path[1:])

            case URL(scheme='file'):
                from ._utils.aio import run_in_thread
                from ._utils.web import file_uri_to_path

                return await run_in_thread(Path(file_uri_to_path(str(url))).read_text)(
                    encoding='utf-8'
                )

            case URL(scheme='http' | 'https'):
                from . import http, http_ctx

                async with http_ctx.web_client().get(
                    url,
                    expire_after=http.CACHE_INDEFINITELY,
                    headers=self.make_request_headers(),
                    raise_for_status=True,
                ) as response:
                    return await response.text()

            case URL() as urly:
                raise ValueError('Unsupported URL with scheme', urly.scheme)

    async def catalogue(self) -> AsyncIterator[CatalogueEntryCandidate]:
        return
        yield
