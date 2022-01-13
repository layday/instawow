from __future__ import annotations

import aiohttp
import pytest

from instawow.github_auth import get_codes, poll_for_access_token


async def test_github_oauth_flow(iw_web_client: aiohttp.ClientSession):
    codes = await get_codes(iw_web_client)
    access_token = await poll_for_access_token(
        iw_web_client, codes['device_code'], codes['interval']
    )
    assert access_token == 'gho_16C7e42F292c6912E7710c838347Ae178B4a'
