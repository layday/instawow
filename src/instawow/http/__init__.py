from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, TypeAlias

import aiohttp

ClientSession: TypeAlias = aiohttp.ClientSession

_USER_AGENT = 'instawow (+https://github.com/layday/instawow)'

_DEFAULT_EXPIRE = 0  # Do not cache by default.
CACHE_INDEFINITELY = -1

_PROGRESS_TICK_INTERVAL = 0.1


@asynccontextmanager
async def _setup_progress_tracker():
    import asyncio

    from .._progress_reporting import get_next_progress_id, update_progress
    from .._utils.aio import cancel_tasks

    progress_tickers = set[asyncio.Task[None]]()

    async def do_on_request_end(
        _client_session: aiohttp.ClientSession,
        trace_config_ctx: Any,
        params: aiohttp.TraceRequestEndParams,
        /,
    ):
        progress = (
            trace_config_ctx.trace_request_ctx and trace_config_ctx.trace_request_ctx['progress']
        )
        if progress:

            async def do_update_progress():
                response = params.response

                progress_id = get_next_progress_id()
                progress['total'] = (
                    None
                    if aiohttp.hdrs.CONTENT_ENCODING in response.headers
                    else response.content_length
                )

                update_progress(progress_id, progress)

                try:
                    while not response.content.is_eof():
                        progress['current'] = response.content.total_bytes
                        update_progress(progress_id, progress)

                        await asyncio.sleep(_PROGRESS_TICK_INTERVAL)

                finally:
                    update_progress(progress_id, 'unset')

            task = asyncio.create_task(do_update_progress())
            task.add_done_callback(progress_tickers.remove)
            progress_tickers.add(task)

    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()

    try:
        yield trace_config
    finally:
        await cancel_tasks(progress_tickers)


@asynccontextmanager
async def init_web_client(
    cache_dir: Path | None, *, no_cache: bool = False, with_progress: bool = False, **kwargs: Any
) -> AsyncIterator[ClientSession]:
    import ssl

    import truststore

    kwargs = {
        'connector': aiohttp.TCPConnector(
            limit_per_host=20, ssl=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ),
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
            from aiohttp_client_cache import CacheBackend
            from aiohttp_client_cache.session import CachedSession

            from ._cache import make_cache

            cache_backend = CacheBackend(
                allowed_codes=(200, 206),
                allowed_methods=('GET', 'POST'),
                expire_after=_DEFAULT_EXPIRE,
                include_headers=True,
            )

            cache = await async_exit_stack.enter_async_context(make_cache(cache_dir))
            cache_backend.responses = cache_backend.redirects = cache
            if no_cache:
                cache_backend.disabled = True

            client_session = await async_exit_stack.enter_async_context(
                CachedSession(cache=cache_backend, **kwargs)
            )
            yield client_session

        else:
            client_session = await async_exit_stack.enter_async_context(
                aiohttp.ClientSession(**kwargs)
            )
            yield client_session
