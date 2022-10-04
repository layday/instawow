from __future__ import annotations

from collections.abc import AsyncIterator, Collection, Iterable, Sequence
from functools import update_wrapper
from pathlib import Path
import typing
from typing import Any, ClassVar, TypeVar
import urllib.parse

from attrs import evolve, frozen
from typing_extensions import Protocol, Self
from yarl import URL

from . import _deferred_types, manager, models, results as R
from .cataloguer import BaseCatalogueEntry
from .common import AddonHashMethod, SourceMetadata, Strategy
from .config import GlobalConfig
from .http import CACHE_INDEFINITELY
from .utils import file_uri_to_path, gather, normalise_names, run_in_thread


@frozen(hash=True)
class Defn:
    source: str
    alias: str
    id: typing.Optional[str] = None
    strategy: Strategy = Strategy.default
    version: typing.Optional[str] = None

    @classmethod
    def from_pkg(cls, pkg: models.Pkg) -> Self:
        return cls(pkg.source, pkg.slug, pkg.id, pkg.options.strategy, pkg.version)

    def with_version(self, version: str) -> Self:
        return evolve(self, strategy=Strategy.version, version=version)


slugify = normalise_names('-')


def format_data_changelog(changelog: str = '') -> str:
    return f'data:,{urllib.parse.quote(changelog)}'


class FolderHashCandidate(Protocol):
    name: str

    def hash_contents(self, __method: AddonHashMethod) -> str:
        ...


TFolderHashCandidate = TypeVar('TFolderHashCandidate', bound=FolderHashCandidate)


class Resolver(Protocol):
    metadata: ClassVar[SourceMetadata]
    requires_access_token: ClassVar[str | None]

    def __init__(self, manager: manager.Manager) -> None:
        ...

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        "Attempt to extract a ``Defn`` alias from a given URL."
        ...

    async def make_auth_headers(self) -> dict[str, str] | None:
        "Create authentication headers."
        ...

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        "Resolve multiple ``Defn``s into packages."
        ...

    async def resolve_one(self, defn: Defn, metadata: Any) -> models.Pkg:
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
    def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        "Enumerate add-ons from the source."
        ...


class BaseResolver(Resolver, Protocol):
    _manager: manager.Manager

    def __init__(self, manager: manager.Manager) -> None:
        self._manager = manager

    __orig_init = __init__

    def __init_subclass__(cls) -> None:
        async def resolve_one(self: Self, defn: Defn, metadata: Any) -> models.Pkg:
            if defn.strategy not in self.metadata.strategies:
                raise R.PkgStrategyUnsupported(defn.strategy)
            return await cls_resolve_one(self, defn, metadata)

        cls.__init__ = cls.__orig_init  # ``Protocol`` clobbers ``__init__`` in Python < 3.11
        cls_resolve_one = cls.resolve_one
        cls.resolve_one = update_wrapper(resolve_one, cls.resolve_one)

    @classmethod
    def _get_access_token(cls, global_config: GlobalConfig) -> str:
        maybe_access_token = None
        if cls.requires_access_token is not None:
            maybe_access_token = getattr(
                global_config.access_tokens, cls.requires_access_token, None
            )
        if maybe_access_token is None:
            raise ValueError(f'{cls.metadata.name} access token is not configured')
        return maybe_access_token

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        return None

    async def make_auth_headers(self) -> dict[str, str] | None:
        return None

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        results = await gather(
            (self.resolve_one(d, None) for d in defns), manager.capture_manager_exc_async
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: Any) -> models.Pkg:
        raise NotImplementedError

    async def get_changelog(self, uri: URL) -> str:
        if uri.scheme == 'data' and uri.raw_path.startswith(','):
            return urllib.parse.unquote(uri.raw_path[1:])
        elif uri.scheme in {'http', 'https'}:
            async with self._manager.web_client.get(
                uri,
                expire_after=CACHE_INDEFINITELY,
                headers=await self.make_auth_headers(),
                raise_for_status=True,
            ) as response:
                return await response.text()
        elif uri.scheme == 'file':
            return await run_in_thread(Path(file_uri_to_path(str(uri))).read_text)(
                encoding='utf-8'
            )
        else:
            raise ValueError('Unsupported URI with scheme', uri.scheme)

    async def get_folder_hash_matches(
        self, candidates: Collection[TFolderHashCandidate]
    ) -> Iterable[tuple[Defn, frozenset[TFolderHashCandidate]]]:
        return []

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        return
        yield
