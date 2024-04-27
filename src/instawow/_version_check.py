from __future__ import annotations

from datetime import timedelta
from typing import TypedDict

from . import config


class _SimpleApiProject(TypedDict):
    versions: list[str]


async def is_outdated(global_config: config.GlobalConfig) -> tuple[bool, str]:
    """Check on PyPI to see if instawow is outdated.

    The response is cached for 24 hours.
    """

    from aiohttp import ClientError
    from packaging.version import Version

    from . import __version__
    from .http import init_web_client

    if not global_config.auto_update_check:
        return (False, '')

    parsed_version = Version(__version__)
    if parsed_version.local:
        return (False, '')

    try:
        async with (
            init_web_client(
                global_config.http_cache_dir,
                raise_for_status=True,
            ) as web_client,
            web_client.get(
                'https://pypi.org/simple/instawow',
                expire_after=timedelta(days=1),
                headers={
                    'Accept': 'application/vnd.pypi.simple.v1+json',
                },
            ) as response,
        ):
            metadata: _SimpleApiProject = await response.json()
            version = max(metadata['versions'], key=Version)
    except ClientError:
        version = __version__

    return (Version(version) > parsed_version, version)
