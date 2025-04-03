from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, overload

import aiohttp
import aiohttp_client_cache
import aiohttp_client_cache.session

type ClientSession = aiohttp.ClientSession
type CachedSession = aiohttp_client_cache.session.CachedSession


_USER_AGENT = 'instawow (+https://github.com/layday/instawow)'

_DEFAULT_EXPIRE = 0  # Do not cache by default.
CACHE_INDEFINITELY = -1

_PROGRESS_TICK_INTERVAL = 0.1


@asynccontextmanager
async def _setup_progress_tracker():
    import asyncio

    from .._utils.aio import cancel_tasks
    from ..progress_reporting import Progress, get_next_progress_id, update_progress

    progress_tickers = set[asyncio.Task[None]]()

    async def do_on_request_end(
        _client_session: aiohttp.ClientSession,
        trace_config_ctx: Any,
        params: aiohttp.TraceRequestEndParams,
        /,
    ):
        progress: Progress[Any] | None = (
            trace_config_ctx.trace_request_ctx
            and trace_config_ctx.trace_request_ctx.get('progress')
        )
        if progress:

            async def do_update_progress():
                response = params.response
                progress_id = get_next_progress_id()
                progress['total'] = total = (
                    None
                    if aiohttp.hdrs.CONTENT_ENCODING in response.headers
                    else response.content_length
                )
                update_progress(progress_id, progress)

                try:
                    if total is None:
                        await response.content.wait_eof()
                    else:
                        while not response.content.is_eof():
                            progress['current'] = response.content.total_bytes
                            update_progress(progress_id, progress)

                            await asyncio.sleep(_PROGRESS_TICK_INTERVAL)

                finally:
                    update_progress(progress_id, 'unset')

            task = asyncio.create_task(do_update_progress())
            progress_tickers.add(task)
            task.add_done_callback(progress_tickers.remove)

    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()

    try:
        yield trace_config
    finally:
        await cancel_tasks(progress_tickers)


def get_ssl_context(cloudflare_compat: bool = False) -> ssl.SSLContext:
    import truststore

    ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if cloudflare_compat:
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3

    return ssl_context


@overload
def init_web_client(
    cache_dir: None, *, no_cache: bool = False, with_progress: bool = False, **kwargs: Any
) -> AbstractAsyncContextManager[ClientSession]: ...
@overload
def init_web_client(
    cache_dir: Path, *, no_cache: bool = False, with_progress: bool = False, **kwargs: Any
) -> AbstractAsyncContextManager[CachedSession]: ...


@asynccontextmanager
async def init_web_client(
    cache_dir: Path | None, *, no_cache: bool = False, with_progress: bool = False, **kwargs: Any
) -> AsyncIterator[ClientSession]:
    kwargs = {
        'connector': aiohttp.TCPConnector(limit_per_host=20, ssl=get_ssl_context()),
        'headers': {'User-Agent': _USER_AGENT},
        'trust_env': True,  # Respect the ``http(s)_proxy`` env var
        'timeout': aiohttp.ClientTimeout(connect=60, sock_connect=10, sock_read=20),
        **kwargs,
    }

    async with AsyncExitStack() as async_exit_stack:
        if with_progress:
            progress_trace_config = await async_exit_stack.enter_async_context(
                _setup_progress_tracker()
            )
            kwargs['trace_configs'] = [*kwargs.get('trace_configs', []), progress_trace_config]

        if cache_dir is not None:
            cache_backend = aiohttp_client_cache.CacheBackend(
                allowed_codes=(200, 206),
                allowed_methods=('GET', 'POST'),
                expire_after=_DEFAULT_EXPIRE,
                include_headers=True,
            )
            if no_cache:
                cache_backend.disabled = True
            else:
                from ._cache import make_cache

                cache_backend.responses = (
                    cache_backend.redirects
                ) = await async_exit_stack.enter_async_context(make_cache(cache_dir))

            client_session = await async_exit_stack.enter_async_context(
                aiohttp_client_cache.session.CachedSession(cache=cache_backend, **kwargs)
            )
            yield client_session

        else:
            client_session = await async_exit_stack.enter_async_context(
                aiohttp.ClientSession(**kwargs)
            )
            yield client_session
