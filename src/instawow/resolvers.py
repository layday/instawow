from __future__ import annotations

import datetime as dt
import enum
from collections.abc import AsyncIterator, Callable, Collection, Iterable, Mapping, Sequence
from functools import cached_property, partial, wraps
from pathlib import Path
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    Never,
    NotRequired,
    Protocol,
    Self,
    TypedDict,
    overload,
)

from typing_extensions import TypeVar
from yarl import URL

from . import pkg_archives
from .catalogue import cataloguer
from .definitions import Defn, SourceMetadata
from .results import (
    AnyResult,
    PkgSourceDisabled,
    PkgSourceInvalid,
    PkgStrategiesUnsupported,
    aresultify,
)

_TTokenRequired = TypeVar('_TTokenRequired', Literal[True], bool)


class AccessTokenMissingError(ValueError):
    def __str__(self) -> str:
        return 'access token missing'


class AccessToken(Generic[_TTokenRequired]):
    def __init__(self, getter: Callable[[], tuple[str | None, _TTokenRequired]]):
        self._getter = getter

    @overload
    def get(self: AccessToken[Literal[True]]) -> str: ...
    @overload
    def get(self: AccessToken[bool]) -> str | None: ...
    def get(self) -> str | None:
        access_token, required = self._getter()
        if required and access_token is None:
            raise AccessTokenMissingError
        return access_token

    @property
    def missing_reason(self) -> str | None:
        access_token, required = self._getter()
        if required and access_token is None:
            return str(AccessTokenMissingError())


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
    deps: NotRequired[list[TypedDict[{'id': str}]]]


class Resolver(Protocol):  # pragma: no cover
    metadata: ClassVar[SourceMetadata]
    'Static source metadata.'

    access_token: ClassVar[AccessToken[bool] | None]
    'Access token retriever.'

    archive_opener: ClassVar[pkg_archives.ArchiveOpener | None]
    'Alternative archive opener to use supporting e.g. non-standard archive formats or layouts.'

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        "Attempt to extract a ``Defn`` alias from a given URL."
        ...

    def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str] | None:
        "Create headers for resolver HTTP requests."
        ...

    async def resolve(self, defns: Sequence[Defn]) -> dict[Defn, AnyResult[PkgCandidate]]:
        "Resolve multiple ``Defn``s into packages."
        ...

    async def resolve_one(self, defn: Defn, metadata: Any) -> PkgCandidate:
        "Resolve a ``Defn`` into a package."
        ...

    async def get_changelog(self, uri: URL) -> str:
        "Retrieve a changelog from a URI."
        ...

    @classmethod
    def catalogue(cls) -> AsyncIterator[cataloguer.CatalogueEntry]:
        "Enumerate add-ons from the source."
        ...


class BaseResolver(Resolver, Protocol):
    access_token = None
    archive_opener = None

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        old_resolve_one = cls.resolve_one
        reassign_resolve_one = partial(setattr, cls, 'resolve_one')

        @reassign_resolve_one
        @wraps(old_resolve_one)
        async def _(self: Self, defn: Defn, metadata: Any):
            extraneous_strategies = defn.strategies.filled.keys() - self.metadata.strategies
            if extraneous_strategies:
                raise PkgStrategiesUnsupported(extraneous_strategies)

            return await old_resolve_one(self, defn, metadata)

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        return None

    def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str] | None:
        return None

    async def resolve(self, defns: Sequence[Defn]) -> dict[Defn, AnyResult[PkgCandidate]]:
        from ._utils.aio import gather
        from .progress_reporting import make_incrementing_progress_tracker

        track_progress = make_incrementing_progress_tracker(
            len(defns), f'Resolving add-ons: {self.metadata.name}'
        )
        results = await gather(
            track_progress(aresultify(self.resolve_one(d, None))) for d in defns
        )
        return dict(zip(defns, results))

    async def get_changelog(self, uri: URL) -> str:
        match uri.scheme:
            case 'data' if uri.raw_path.startswith(','):
                import urllib.parse

                return urllib.parse.unquote(uri.raw_path[1:])

            case 'file':
                from ._utils.aio import run_in_thread
                from ._utils.web import file_uri_to_path

                return await run_in_thread(Path(file_uri_to_path(str(uri))).read_text)(
                    encoding='utf-8'
                )

            case 'http' | 'https':
                from . import http, http_ctx

                async with http_ctx.web_client().get(
                    uri,
                    expire_after=http.CACHE_INDEFINITELY,
                    headers=self.make_request_headers(),
                    raise_for_status=True,
                ) as response:
                    return await response.text()

            case _:
                raise ValueError('Unsupported URI with scheme', uri.scheme)

    @classmethod
    async def catalogue(cls) -> AsyncIterator[cataloguer.CatalogueEntry]:
        return
        yield


class Resolvers(dict[str, Resolver]):
    def __init__(self, resolvers: Iterable[type[Resolver]]):
        super().__init__((r.metadata.id, r()) for r in resolvers)

    def get_or_dummy(self, key: str) -> Resolver:
        if key in self.disabled_resolver_reasons:
            error = PkgSourceDisabled(self.disabled_resolver_reasons[key])
        elif key in self:
            return self[key]
        else:
            error = PkgSourceInvalid()

        @object.__new__
        class DummyResolver(Resolver):
            async def resolve(self, defns: Sequence[Defn]) -> dict[Defn, AnyResult[PkgCandidate]]:
                return dict.fromkeys(defns, error)

            async def get_changelog(self, uri: URL) -> Never:
                raise error

        return DummyResolver

    @cached_property
    def addon_toc_key_and_id_pairs(self) -> Collection[tuple[str, str]]:
        return [
            (r.metadata.addon_toc_key, r.metadata.id)
            for r in self.values()
            if r.metadata.addon_toc_key
        ]

    @cached_property
    def archive_opener_dict(self) -> _ResolverArchiveOpenerDict:
        return _ResolverArchiveOpenerDict(self)

    @cached_property
    def disabled_resolver_reasons(self) -> Mapping[str, str]:
        return {
            r.metadata.id: d
            for r in self.values()
            if r.access_token
            for d in (r.access_token.missing_reason,)
            if d
        }

    @cached_property
    def priority_dict(self) -> _ResolverPriorityDict:
        return _ResolverPriorityDict(self)


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
