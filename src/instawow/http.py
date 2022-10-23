from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from typing_extensions import TypeAlias, TypedDict

from . import _deferred_types, models
from .utils import read_resource_as_text

_USER_AGENT = 'instawow (+https://github.com/layday/instawow)'

_DEFAULT_EXPIRE = 0  # Do not cache by default.

CACHE_INDEFINITELY = -1


class _GenericDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['generic']
    label: str


class _PkgDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['pkg_download']
    profile: str
    pkg: models.Pkg


TraceRequestCtx: TypeAlias = '_GenericDownloadTraceRequestCtx | _PkgDownloadTraceRequestCtx | None'


def make_pkg_progress_ctx(profile: str, pkg: models.Pkg) -> _PkgDownloadTraceRequestCtx:
    return {'report_progress': 'pkg_download', 'profile': profile, 'pkg': pkg}


def make_generic_progress_ctx(label: str) -> _GenericDownloadTraceRequestCtx:
    return {'report_progress': 'generic', 'label': label}


@lru_cache(1)
def _load_certifi_certs():
    try:
        import certifi
    except ModuleNotFoundError:
        pass
    else:
        logger.info('loading certifi certs')
        return read_resource_as_text(certifi, 'cacert.pem', encoding='ascii')


@asynccontextmanager
async def init_web_client(
    cache_dir: Path | None, **kwargs: Any
) -> AsyncIterator[_deferred_types.aiohttp.ClientSession]:
    from aiohttp import ClientSession, ClientTimeout, TCPConnector

    make_connector = partial(TCPConnector, limit_per_host=10)
    certifi_certs = _load_certifi_certs()
    if certifi_certs:
        import ssl

        make_connector = partial(
            make_connector, ssl=ssl.create_default_context(cadata=certifi_certs)
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

        from ._http_cache_db import SQLiteBackend, acquire_cache_db_conn

        with acquire_cache_db_conn(cache_dir / '_aiohttp-cache.sqlite') as db_conn:
            async with CachedSession(
                cache=SQLiteBackend(
                    allowed_codes=[200, 206],
                    allowed_methods=['GET', 'POST'],
                    db_conn=db_conn,
                    expire_after=_DEFAULT_EXPIRE,
                    include_headers=True,
                ),
                **kwargs,
            ) as client_session:
                yield client_session
    else:
        async with ClientSession(**kwargs) as client_session:
            yield client_session
