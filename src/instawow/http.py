from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger
from typing_extensions import TypeAlias, TypedDict

from . import common

if TYPE_CHECKING:
    import aiohttp

    ClientSessionType: TypeAlias = aiohttp.ClientSession
else:
    ClientSessionType = type

_USER_AGENT = 'instawow (+https://github.com/layday/instawow)'

_DEFAULT_EXPIRE = 0  # Do not cache by default.

CACHE_INDEFINITELY = -1


class _GenericDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['generic']
    label: str


class _DefnDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['pkg_download']
    profile: str
    defn: common.Defn


TraceRequestCtx: TypeAlias = (
    '_GenericDownloadTraceRequestCtx | _DefnDownloadTraceRequestCtx | None'
)


def make_generic_progress_ctx(label: str) -> _GenericDownloadTraceRequestCtx:
    return {'report_progress': 'generic', 'label': label}


def make_defn_progress_ctx(profile: str, defn: common.Defn) -> _DefnDownloadTraceRequestCtx:
    return {'report_progress': 'pkg_download', 'profile': profile, 'defn': defn}


@asynccontextmanager
async def init_web_client(
    cache_dir: Path | None, *, no_cache: bool = False, **kwargs: Any
) -> AsyncIterator[ClientSessionType]:
    from aiohttp import ClientSession, ClientTimeout, TCPConnector

    make_connector = partial(TCPConnector, limit_per_host=10)

    if sys.version_info >= (3, 10):
        import ssl

        import truststore

        logger.info('using truststore')

        make_connector = partial(
            make_connector, ssl=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        )

    kwargs = {
        'connector': make_connector(),
        'headers': {'User-Agent': _USER_AGENT},
        'trust_env': True,  # Respect the ``http(s)_proxy`` env var
        'timeout': ClientTimeout(connect=60, sock_connect=10, sock_read=20),
        **kwargs,
    }

    if cache_dir is not None:
        from aiohttp_client_cache.session import CachedSession

        from ._http_cache_db import SQLiteBackend, acquire_cache_connection

        with acquire_cache_connection(cache_dir) as connection:
            cache_backend = SQLiteBackend(
                allowed_codes=[200, 206],
                allowed_methods=['GET', 'POST'],
                connection=connection,
                expire_after=_DEFAULT_EXPIRE,
                include_headers=True,
            )
            if no_cache:
                cache_backend.disabled = True

            async with CachedSession(
                cache=cache_backend,
                **kwargs,
            ) as client_session:
                yield client_session
    else:
        async with ClientSession(**kwargs) as client_session:
            yield client_session
