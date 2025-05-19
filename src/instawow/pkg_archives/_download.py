from __future__ import annotations

from contextlib import asynccontextmanager, nullcontext
from functools import partial
from pathlib import Path
from shutil import move
from tempfile import NamedTemporaryFile
from typing import Literal

from .. import config_ctx, http, http_ctx, sync_ctx
from .._utils.aio import run_in_thread
from .._utils.file import make_instawowt
from .._utils.web import file_uri_to_path, is_file_uri
from ..definitions import Defn
from ..progress_reporting import Progress
from ..resolvers import HeadersIntent


class PkgDownloadProgress(Progress[Literal['pkg_download'], Literal['bytes']]):
    profile: str
    defn: Defn


_DOWNLOAD_PKG_LOCK = '_DOWNLOAD_PKG_'

_AsyncNamedTemporaryFile = run_in_thread(NamedTemporaryFile)
_move_async = run_in_thread(move)
_make_instawowt_async = run_in_thread(make_instawowt)

_alt_ssl_context = http.get_ssl_context(cloudflare_compat=True)


@asynccontextmanager
async def _open_temp_writer_async():
    fh = await _AsyncNamedTemporaryFile(
        delete=False, dir=await _make_instawowt_async(), prefix='download-'
    )
    path = Path(fh.name)
    try:
        yield (path, run_in_thread(fh.write))
    except BaseException:
        await run_in_thread(fh.close)()
        await run_in_thread(path.unlink)()
        raise
    else:
        await run_in_thread(fh.close)()


async def download_pkg_archive(defn: Defn, download_url: str) -> Path:
    if is_file_uri(download_url):
        return Path(file_uri_to_path(download_url))

    async with sync_ctx.locks()[_DOWNLOAD_PKG_LOCK, download_url]:
        make_request = partial(
            http_ctx.web_client().get,
            download_url,
            expire_after=http.CACHE_INDEFINITELY,
            headers=config_ctx.resolvers()[defn.source].make_request_headers(
                intent=HeadersIntent.Download
            ),
            trace_request_ctx={
                'progress': PkgDownloadProgress(
                    type_='pkg_download',
                    unit='bytes',
                    current=0,
                    total=0,
                    profile=config_ctx.config().profile,
                    defn=defn,
                )
            },
        )

        async with make_request() as response:
            # CloudFlare seems to think the default combination of TLS 1.2 and 1.3
            # is unacceptable: https://github.com/aio-libs/aiohttp/discussions/9300#discussioncomment-10775829
            if response.status == 403 and 'CF-RAY' in response.headers:
                repeat_request = partial(make_request, ssl=_alt_ssl_context)
            else:

                def repeat_request_():
                    return nullcontext(response)

                repeat_request = repeat_request_

            async with repeat_request() as response:
                response.raise_for_status()

                async with _open_temp_writer_async() as (temp_path, write):
                    async for chunk, _ in response.content.iter_chunks():
                        await write(chunk)

        return temp_path
