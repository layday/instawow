from __future__ import annotations

import importlib.metadata

import aiohttp.web
import pytest

from instawow._version import get_version, is_outdated

from ._fixtures.http import AddRoutes, Route


def test_get_version_same_as_importlib():
    assert get_version() == importlib.metadata.version('instawow')


def test_get_dummy_version_when_metadata_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr('sys.path', [])
    assert get_version() == '0+dev'


@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [set()],
    indirect=True,
)
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_is_outdated_works_in_variety_of_scenarios(
    monkeypatch: pytest.MonkeyPatch,
    iw_add_routes: AddRoutes,
):
    # Endpoint not responsive, version not cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow._version.get_version', lambda: '0.1.0')
        iw_add_routes(
            Route(
                r'//pypi\.org/simple/instawow',
                lambda: aiohttp.web.Response(status=500),
                single_use=True,
            )
        )
        assert await is_outdated() == (False, '0.1.0')

    # Endpoint responsive, version not cached and version different
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow._version.get_version', lambda: '0.1.0')
        iw_add_routes(
            Route(r'//pypi\.org/simple/instawow', {'versions': ['1.0.0']}, single_use=True)
        )
        assert await is_outdated() == (True, '1.0.0')

    # version == '0+dev', version cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow._version.get_version', lambda: '0+dev')
        assert await is_outdated() == (False, '')

    # Endpoint not responsive, version cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow._version.get_version', lambda: '0.1.0')
        iw_add_routes(
            Route(
                r'//pypi\.org/simple/instawow',
                lambda: aiohttp.web.Response(status=500),
                single_use=True,
            )
        )
        assert await is_outdated() == (True, '1.0.0')

    # Endpoint responsive, version cached and version same
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow._version.get_version', lambda: '0.1.0')
        iw_add_routes(
            Route(r'//pypi\.org/simple/instawow', {'versions': ['1.0.0']}, single_use=True)
        )
        assert await is_outdated() == (True, '1.0.0')

    # Endpoint responsive, version cached and version different
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow._version.get_version', lambda: '1.0.0')
        iw_add_routes(
            Route(r'//pypi\.org/simple/instawow', {'versions': ['1.0.0']}, single_use=True)
        )
        assert await is_outdated() == (False, '1.0.0')
