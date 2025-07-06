"""
Trimmed down version of aresponses.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from functools import partial
from typing import Protocol
from unittest import mock

import attrs
import pytest
from aiohttp.abc import ResolveResult
from aiohttp.connector import TCPConnector
from aiohttp.test_utils import BaseTestServer, RawTestServer
from aiohttp.tracing import Trace
from aiohttp.web import Response as Response
from aiohttp.web_request import BaseRequest
from aiohttp.web_response import json_response
from yarl import URL

type _Response = (
    Callable[[], Response]
    | Callable[[BaseRequest], Awaitable[Response]]
    | dict[str, object]
    | list[object]
    | str
)


class AddRoutes(Protocol):
    def __call__(self, *routes: Route) -> None: ...


class NoRouteFoundError(AssertionError):
    pass


@attrs.frozen
class Route:
    url: URL = attrs.field(converter=URL)
    response: _Response
    method: str = attrs.field(converter=str.upper, default='GET')
    single_use: bool = False
    path_qs_pattern: re.Pattern[str] = attrs.field(init=False)

    def __attrs_post_init__(self):
        object.__setattr__(self, 'path_qs_pattern', re.compile(self.url.path_qs, re.IGNORECASE))

    def matches(self, request: BaseRequest):
        if self.method != request.method:
            return False
        elif self.url.host != re.escape(request.host):
            return False
        elif not self.path_qs_pattern.fullmatch(request.path_qs):
            return False
        return True


def prepare_mock_server_router():
    async def match_route(request: BaseRequest) -> Response:
        for i, route in enumerate(routes):
            if not route.matches(request):
                continue

            if route.single_use:
                del routes[i]

            match route.response:
                case Callable() as fn:
                    return await fn(request) if inspect.iscoroutinefunction(fn) else fn()  # pyright: ignore  # noqa: PGH003
                case str() as text:
                    return Response(body=text)
                case (dict() | list()) as json:
                    return json_response(data=json)
                case _:
                    raise ValueError(f'Unsupported response type: {type(route.response)}')

        else:
            raise NoRouteFoundError(f'No match found for <{request.method} {request.url}>')

    routes = list[Route]()

    def add_routes(*routes_: Route) -> None:
        routes.extend(routes_)

    return partial(RawTestServer, handler=match_route), add_routes


def patch_aiohttp(patcher: pytest.MonkeyPatch, mock_server: BaseTestServer):
    @partial(patcher.setattr, 'aiohttp.TCPConnector')
    class _(TCPConnector):
        async def _resolve_host(
            self, host: str, port: int, traces: Sequence[Trace] | None = None
        ) -> list[ResolveResult]:
            return [
                {
                    'hostname': host,
                    'host': '127.0.0.1',
                    'port': mock_server.port,  # pyright: ignore[reportReturnType]
                    'family': self._family,
                    'proto': 0,
                    'flags': 0,
                }
            ]

    patcher.setattr('aiohttp.ClientRequest.is_ssl', mock.Mock(return_value=False))
