from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from shutil import move
from tempfile import NamedTemporaryFile
from typing import Literal

from .. import http, shared_ctx
from .._progress_reporting import Progress
from .._utils.aio import run_in_thread
from .._utils.text import shasum
from .._utils.web import file_uri_to_path, is_file_uri
from ..definitions import Defn
from ..resolvers import HeadersIntent


class PkgDownloadProgress(Progress[Literal['pkg_download'], Literal['bytes']]):
    profile: str
    defn: Defn


_DOWNLOAD_PKG_LOCK = '_DOWNLOAD_PKG_'

_AsyncNamedTemporaryFile = run_in_thread(NamedTemporaryFile)
_move_async = run_in_thread(move)


@asynccontextmanager
async def _open_temp_writer_async():
    fh = await _AsyncNamedTemporaryFile(delete=False)
    path = Path(fh.name)
    try:
        yield (path, run_in_thread(fh.write))
    except BaseException:
        await run_in_thread(fh.close)()
        await run_in_thread(path.unlink)()
        raise
    else:
        await run_in_thread(fh.close)()


async def download_pkg_archive(
    config_ctx: shared_ctx.ConfigBoundCtx, defn: Defn, download_url: str
) -> Path:
    if is_file_uri(download_url):
        return Path(file_uri_to_path(download_url))

    async with shared_ctx.locks[_DOWNLOAD_PKG_LOCK, download_url]:
        headers = config_ctx.resolvers[defn.source].make_request_headers(
            intent=HeadersIntent.Download
        )
        trace_request_ctx = {
            'progress': PkgDownloadProgress(
                type_='pkg_download',
                unit='bytes',
                current=0,
                total=0,
                profile=config_ctx.config.profile,
                defn=defn,
            )
        }

        async with (
            shared_ctx.web_client.get(
                download_url,
                headers=headers,
                raise_for_status=True,
                trace_request_ctx=trace_request_ctx,
                expire_after=http.CACHE_INDEFINITELY,
            ) as response,
            _open_temp_writer_async() as (temp_path, write),
        ):
            async for chunk, _ in response.content.iter_chunks():
                await write(chunk)

        return await _move_async(
            temp_path, config_ctx.config.global_config.install_cache_dir / shasum(download_url)
        )
