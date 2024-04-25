from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Literal, TypeAlias

from typing_extensions import Never, TypedDict, TypeVar

if TYPE_CHECKING:
    import aiohttp

    ClientSessionType: TypeAlias = aiohttp.ClientSession
else:
    ClientSessionType = type

_USER_AGENT = 'instawow (+https://github.com/layday/instawow)'

_DEFAULT_EXPIRE = 0  # Do not cache by default.

CACHE_INDEFINITELY = -1


_TProgress = TypeVar('_TProgress', bound=str)
_TProgressCtx = TypeVar('_TProgressCtx', bound='ProgressCtx[Any]', default=Never)


class ProgressCtx(TypedDict, Generic[_TProgress]):
    report_progress: _TProgress


class GenericDownloadTraceRequestCtx(ProgressCtx[Literal['generic']]):
    label: str


TraceRequestCtx: TypeAlias = GenericDownloadTraceRequestCtx | _TProgressCtx | None


@asynccontextmanager
async def init_web_client(
    cache_dir: Path | None, *, no_cache: bool = False, **kwargs: Any
) -> AsyncIterator[ClientSessionType]:
    import ssl

    import truststore
    from aiohttp import ClientSession, ClientTimeout, TCPConnector

    connector = TCPConnector(limit_per_host=10, ssl=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))

    kwargs = {
        'connector': connector,
        'headers': {'User-Agent': _USER_AGENT},
        'trust_env': True,  # Respect the ``http(s)_proxy`` env var
        'timeout': ClientTimeout(connect=60, sock_connect=10, sock_read=20),
        **kwargs,
    }

    if cache_dir is not None:
        from aiohttp_client_cache import CacheBackend
        from aiohttp_client_cache.session import CachedSession

        from ._cache import make_cache

        cache_backend = CacheBackend(
            allowed_codes=(200, 206),
            allowed_methods=('GET', 'POST'),
            expire_after=_DEFAULT_EXPIRE,
            include_headers=True,
        )
        async with make_cache(cache_dir) as cache:
            cache_backend.responses = cache_backend.redirects = cache
            if no_cache:
                cache_backend.disabled = True

            async with CachedSession(cache=cache_backend, **kwargs) as client_session:
                yield client_session

    else:
        async with ClientSession(**kwargs) as client_session:
            yield client_session
