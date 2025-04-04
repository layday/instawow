from __future__ import annotations

from typing import TypedDict

from . import NAME, http_ctx


def get_version() -> str:
    from ._utils.dist_metadata import DistNotFoundError, get_version

    try:
        return get_version(NAME)
    except DistNotFoundError:
        return '0+dev'


async def is_outdated(current_version: str | None = None) -> tuple[bool, str]:
    """Check on PyPI to see if instawow is outdated.

    The response is cached for 24 hours.
    """
    from datetime import timedelta

    from aiohttp import ClientError
    from packaging.version import Version

    __version__ = current_version or get_version()
    parsed_version = Version(__version__)
    if parsed_version.local:
        return (False, '')

    try:
        async with http_ctx.web_client().get(
            'https://pypi.org/simple/instawow',
            expire_after=timedelta(days=1),
            headers={
                'Accept': 'application/vnd.pypi.simple.v1+json',
            },
            raise_for_status=True,
        ) as response:
            metadata: TypedDict[{'versions': list[str]}] = await response.json()

    except ClientError:
        version = __version__
    else:
        version = max(metadata['versions'], key=Version)

    return (Version(version) > parsed_version, version)
