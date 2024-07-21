from __future__ import annotations

from functools import partial
from types import SimpleNamespace
from typing import Generic, Literal, Protocol, TypeVar, cast, overload

from .. import config
from ..resolvers import BaseResolver

_TTokenValue = TypeVar('_TTokenValue', covariant=True)


class _AccessToken(Protocol):  # pragma: no cover
    name: str
    required: str


class _AccessTokenOnInstance(_AccessToken, Protocol[_TTokenValue]):  # pragma: no cover
    def get(self) -> _TTokenValue: ...


class _AccessTokenOnClass(_AccessToken, Protocol[_TTokenValue]):  # pragma: no cover
    def get(self, global_config: config.GlobalConfig) -> _TTokenValue: ...


class AccessToken(Generic[_TTokenValue]):
    @overload
    def __init__(self: AccessToken[str], name: str, required: Literal[True]) -> None: ...
    @overload
    def __init__(self: AccessToken[str | None], name: str, required: Literal[False]) -> None: ...

    def __init__(self, name: str, required: bool) -> None:
        self.name = name
        self.required = required

    @overload
    def __get__(
        self, instance: BaseResolver, owner: object = None
    ) -> _AccessTokenOnInstance[_TTokenValue]: ...
    @overload
    def __get__(
        self, instance: None, owner: object = None
    ) -> _AccessTokenOnClass[_TTokenValue]: ...

    def __get__(self, instance: BaseResolver | None, owner: object = None):
        def get(global_config: config.GlobalConfig):
            access_token = getattr(global_config.access_tokens, self.name)
            if self.required and access_token is None:
                raise ValueError('access token is not configured')
            return access_token

        value = partial(SimpleNamespace, **self.__dict__)
        if instance:
            return cast(
                _AccessTokenOnClass[_TTokenValue],
                value(get=partial(get, instance._config.global_config)),  # pyright: ignore[reportPrivateUsage]
            )
        else:
            return cast(_AccessTokenOnInstance[_TTokenValue], value(get=get))
