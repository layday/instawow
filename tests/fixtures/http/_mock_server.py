"""
Trimmed down version of aresponses.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from copy import copy
from typing import Any

import attrs
from aiohttp.connector import TCPConnector
from aiohttp.test_utils import RawTestServer
from aiohttp.tracing import Trace
from aiohttp.web import Response
from aiohttp.web_request import BaseRequest
from aiohttp.web_response import json_response
from yarl import URL

_Response = (
    Response
    | Callable[[BaseRequest], Response]
    | Callable[[BaseRequest], Awaitable[Response]]
    | dict[str, Any]
    | list[Any]
    | str
)


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


class ResponsesMockServer(RawTestServer):
    def __init__(self, **kwargs: Any):
        super().__init__(handler=self.__find_response, **kwargs)
        self.__routes = list[Route]()

    async def __find_response(self, request: BaseRequest) -> Response:
        for i, route in enumerate(self.__routes):
            if not route.matches(request):
                continue

            if route.single_use:
                del self.__routes[i]

            match route.response:
                case Callable() as fn:
                    return await fn(request) if asyncio.iscoroutinefunction(fn) else fn(request)  # pyright: ignore[reportReturnType]
                case str() as text:
                    return Response(body=text)
                case (dict() | list()) as json:
                    return json_response(data=json)
                case prepared_response:
                    return copy(prepared_response)
        else:
            raise NoRouteFoundError(f'No match found for <{request.method} {request.url}>')

    def add(self, *routes: Route) -> None:
        self.__routes.extend(routes)

    @property
    def tcp_connector_class(self) -> type[TCPConnector]:
        class _TCPConnector(TCPConnector):
            async def _resolve_host(
                _self: TCPConnector, host: str, port: int, traces: Sequence[Trace] | None = None
            ) -> Any:
                return [
                    {
                        'hostname': host,
                        'host': '127.0.0.1',
                        'port': self.port,  # pyright: ignore[reportUnknownMemberType]
                        'family': _self._family,
                        'proto': 0,
                        'flags': 0,
                    }
                ]

        return _TCPConnector
