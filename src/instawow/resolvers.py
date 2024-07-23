from __future__ import annotations

import datetime as dt
import enum
from collections.abc import AsyncIterator, Collection, Mapping, Sequence
from functools import cached_property
from pathlib import Path
from typing import Any, ClassVar, Protocol, TypedDict

from typing_extensions import Never, NotRequired
from yarl import URL

from . import config, pkg_archives, pkg_models
from .catalogue import cataloguer
from .definitions import Defn, SourceMetadata
from .results import (
    InternalError,
    ManagerError,
    PkgSourceDisabled,
    PkgSourceInvalid,
    PkgStrategiesUnsupported,
    resultify_async_exc,
)


class HeadersIntent(enum.IntEnum):
    Download = enum.auto()


class Resolver(Protocol):  # pragma: no cover
    metadata: ClassVar[SourceMetadata]
    'Static source metadata.'

    archive_opener: ClassVar[pkg_archives.ArchiveOpener | None]
    'Alternative archive opener to use supporting e.g. non-standard archive formats or layouts.'

    def __init__(self, config: config.ProfileConfig) -> None: ...

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        "Attempt to extract a ``Defn`` alias from a given URL."
        ...

    def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str] | None:
        "Create headers for resolver HTTP requests."
        ...

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, pkg_models.Pkg | ManagerError | InternalError]:
        "Resolve multiple ``Defn``s into packages."
        ...

    async def resolve_one(self, defn: Defn, metadata: Any) -> pkg_models.Pkg:
        "Resolve a ``Defn`` into a package."
        ...

    async def get_changelog(self, uri: URL) -> str:
        "Retrieve a changelog from a URI."
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
    _config: config.ProfileConfig

    archive_opener = None

    def __init__(self, config: config.ProfileConfig) -> None:
        self._config = config

    __orig_init = __init__

    def __init_subclass__(cls) -> None:
        # ``Protocol`` clobbers ``__init__`` on Python < 3.11.
        if cls.__init__ is _ConcreteResolver.__init__:
            cls.__init__ = cls.__orig_init

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        return None

    def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str] | None:
        return None

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, pkg_models.Pkg | ManagerError | InternalError]:
        from ._progress_reporting import make_incrementing_progress_tracker
        from ._utils.aio import gather

        track_progress = make_incrementing_progress_tracker(
            len(defns), f'Resolving add-ons: {self.metadata.name}'
        )
        results = await gather(
            track_progress(resultify_async_exc(self.resolve_one(d, None))) for d in defns
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: Any) -> pkg_models.Pkg:
        extraneous_strategies = defn.strategies.filled.keys() - self.metadata.strategies
        if extraneous_strategies:
            raise PkgStrategiesUnsupported(extraneous_strategies)

        pkg_candidate = await self._resolve_one(defn, metadata)
        return pkg_models.Pkg(
            **pkg_candidate,
            source=self.metadata.id,
            options=pkg_models.PkgOptions(**{k: bool(v) for k, v in defn.strategies.items()}),
        )

    async def _resolve_one(self, defn: Defn, metadata: Any) -> PkgCandidate:  # pragma: no cover
        "Resolve a ``Defn`` into a package."
        ...

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
                from . import http, shared_ctx

                async with shared_ctx.web_client.get(
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


class _ConcreteResolver(Resolver):
    pass


class Resolvers(dict[str, Resolver]):
    def __init__(
        self, resolvers: Mapping[str, Resolver], disabled_resolver_reasons: Mapping[str, str]
    ):
        super().__init__(resolvers)
        self.disabled_resolver_reasons: Mapping[str, str] = disabled_resolver_reasons

    def get_or_dummy(self, key: str) -> Resolver:
        if key in self.disabled_resolver_reasons:
            error = PkgSourceDisabled(self.disabled_resolver_reasons[key])
        elif key in self:
            return self[key]
        else:
            error = PkgSourceInvalid()

        @object.__new__
        class DummyResolver(Resolver):
            async def resolve(
                self, defns: Sequence[Defn]
            ) -> dict[Defn, pkg_models.Pkg | ManagerError | InternalError]:
                return dict.fromkeys(defns, error)

            async def get_changelog(self, uri: URL) -> Never:
                raise error

        return DummyResolver

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
