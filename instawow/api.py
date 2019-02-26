
from __future__ import annotations

import abc
from datetime import datetime
from enum import Enum, IntEnum
from functools import partial
from json import JSONDecodeError, JSONEncoder, loads
from pathlib import Path
from typing import (Any, Awaitable, Callable, ClassVar, Dict, Generator,
                    List, Optional, Tuple, Union)

from pydantic import BaseModel, Extra, StrictStr, ValidationError, validator
from pydantic.errors import IntegerError

from .manager import Manager
from .models import *


__all__ = ('ErrorCodes', 'ApiError',
           'Request', 'ResolveRequest', 'InstallRequest', 'UpdateRequest',
           'RemoveRequest', 'GetRequest',
           'SuccessResponse', 'ErrorResponse',
           'jsonify', 'parse_request')


JSONRPC_VERSION = '2.0'


class ErrorCodes(IntEnum):

    PARSE_ERROR                    = -32700
    INVALID_REQUEST                = -32600
    METHOD_NOT_FOUND               = -32601
    INVALID_PARAMS                 = -32602
    INTERNAL_ERROR                 = -32603

    MANAGER_ERROR                  = +10000
    PKG_ALREADY_INSTALLED          = +10001
    PKG_CONFLICTS_WITH_INSTALLED   = +10002
    PKG_CONFLICTS_WITH_PREEXISTING = +10003
    PKG_NONEXISTENT                = +10004
    PKG_TEMPORARILY_UNAVAILABLE    = +10005
    PKG_NOT_INSTALLED              = +10006
    PKG_ORIGIN_INVALID             = +10007
    PKG_UP_TO_DATE                 = +10008

    ManagerError                   = +10000
    PkgAlreadyInstalled            = +10001
    PkgConflictsWithInstalled      = +10002
    PkgConflictsWithPreexisting    = +10003
    PkgNonexistent                 = +10004
    PkgTemporarilyUnavailable      = +10005
    PkgNotInstalled                = +10006
    PkgOriginInvalid               = +10007
    PkgUpToDate                    = +10008


class ResolutionStrategies(str, Enum):

    canonical = 'canonical'
    latest = 'latest'


class _ApiErrorMeta(type):

    def __getattr__(cls, name: str) -> Callable:
        return partial(ApiError, ErrorCodes[name])


class ApiError(Exception, metaclass=_ApiErrorMeta):

    def __init__(self,
                 error_code: ErrorCodes,
                 message: str,
                 data: Optional[str]=None,
                 request_id: Union[None, int, str]=None) -> None:
        self.error_code = error_code
        self.message = message
        self.data = data
        self.request_id = request_id


class _IncompatibleMethodError(ValueError):
    pass


def validate_const(const):
    "A validator mirroring JSON Schema's ``const``."
    def is_equal(cls, value):
        if value != const:
            raise _IncompatibleMethodError
        return value

    is_equal.__qualname__ = f'is_equal_{id(is_equal)}'    # Needed to fool pydantic's validator registry
    return is_equal


def decompose_pkg_uri(manager: Manager, uri: str) -> Tuple[str, str]:
    "Turn a URI into an origin–slug pair."
    return next(filter(None, (r.decompose_url(uri)
                              for r in manager.resolvers.values())),
                uri.partition(':')[::2])


class Message(BaseModel,
              abc.ABC):

    jsonrpc: str

    __is_jsonrpc_const = validator('jsonrpc')(validate_const(JSONRPC_VERSION))


class StrictInt(int):

    @classmethod
    def __get_validators__(cls) -> Generator:
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> int:
        if type(v) is not int:      # isintance(bool(), int) == True
            raise IntegerError
        return v


class RequestParams(BaseModel):
    pass


class Request(Message,
              abc.ABC):

    _name: ClassVar[str]

    id: Union[StrictInt, StrictStr]
    method: str
    params: RequestParams

    def prepare_response(self, manager: Manager) -> Awaitable:
        raise NotImplementedError

    def consume_result(self, result: Any) -> SuccessResponse:
        raise NotImplementedError


class BaseRequestParams(RequestParams):

    class Config:
        extra = Extra.allow


class BaseRequest(Request):

    _name = '!base_request'

    params: BaseRequestParams = BaseRequestParams()


class ResolveRequestParams(RequestParams):

    uri: str
    resolution_strategy: ResolutionStrategies

    class Config:
        use_enum_values = True


class ResolveRequest(Request):

    _name = 'resolve'

    params: ResolveRequestParams

    __is_method_const = validator('method')(validate_const('resolve'))

    def prepare_response(self, manager: Manager) -> Awaitable:
        return manager.resolve(*decompose_pkg_uri(manager, self.params.uri),
                               self.params.resolution_strategy)

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=result, id=self.id)


class InstallRequestParams(RequestParams):

    uri: str
    resolution_strategy: ResolutionStrategies
    overwrite: bool

    class Config:
        use_enum_values = True


class InstallRequest(Request):

    _name = 'install'

    params: InstallRequestParams

    __is_method_const = validator('method')(validate_const('install'))

    def prepare_response(self, manager: Manager) -> Awaitable:
        return manager.to_install(*decompose_pkg_uri(manager, self.params.uri),
                                  self.params.resolution_strategy,
                                  self.params.overwrite)

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=None, id=self.id)


class UpdateRequestParams(RequestParams):

    uri: str


class UpdateRequest(Request):

    _name = 'update'

    params: UpdateRequestParams

    __is_method_const = validator('method')(validate_const('update'))

    def prepare_response(self, manager: Manager) -> Awaitable:
        return manager.to_update(*decompose_pkg_uri(manager, self.params.uri))

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=None, id=self.id)


class RemoveRequestParams(RequestParams):

    uri: str


class RemoveRequest(Request):

    _name = 'remove'

    params: RemoveRequestParams

    __is_method_const = validator('method')(validate_const('remove'))

    def prepare_response(self, manager: Manager) -> Awaitable:
        return manager.remove(*decompose_pkg_uri(manager, self.params.uri))

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=None, id=self.id)


class GetRequestParams(RequestParams):

    uris: List[str]


class GetRequest(Request):

    _name = 'get'

    params: GetRequestParams

    __is_method_const = validator('method')(validate_const('get'))

    def prepare_response(self, manager: Manager) -> Awaitable:
        async def get() -> list:
            if self.params.uris:
                return [manager.get(*decompose_pkg_uri(manager, u))
                        for u in self.params.uris]
            return manager.db.query(Pkg).all()

        return get()

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=result, id=self.id)


class Response(Message,
               abc.ABC):

    jsonrpc = JSONRPC_VERSION
    id: Union[None, StrictInt, StrictStr]


class SuccessResponse(Response):

    result: Any


class Error(BaseModel):

    code: ErrorCodes
    message: str
    data: Optional[str]

    class Config:
        use_enum_values = True


class ErrorResponse(Response):

    error: Error

    @classmethod
    def from_api_error(cls, api_error: ApiError) -> ErrorResponse:
        return cls(id=api_error.request_id, error=Error(code=api_error.error_code,
                                                        message=api_error.message,
                                                        data=api_error.data))


def _convert_sqla_obj(obj: Union[Pkg, PkgFolder, PkgOptions]) -> dict:
    models = {Pkg: (PkgCoercer, [*PkgCoercer.__fields__, 'folders', 'options']),
              PkgFolder: (PkgFolderCoercer, ['path']),
              PkgOptions: (PkgOptionsCoercer, ['strategy'])}

    coercer, fields = models[obj.__class__]
    return coercer.parse_obj({f: getattr(obj, f) for f in fields}).dict()


class Encoder(JSONEncoder):

    def default(self, value: Any) -> Any:
        for type_, typecast in [(Pkg, _convert_sqla_obj),
                                (PkgFolder, _convert_sqla_obj),
                                (PkgOptions, _convert_sqla_obj),
                                (Message, BaseModel.dict),
                                (Path, str),
                                (datetime, datetime.isoformat),]:
            if isinstance(value, type_):
                return typecast(value)
        return super().default(value)


jsonify = Encoder().encode


_REQUESTS = {r._name: r for r in  {ResolveRequest, InstallRequest, UpdateRequest,
                                   RemoveRequest, GetRequest}}


def parse_request(message: str) -> Request:
    "Parse a JSON request into a ``Request`` object."
    try:
        base_request = BaseRequest.parse_obj(loads(message))
    except JSONDecodeError as error:
        raise ApiError.PARSE_ERROR('request is not valid JSON', str(error))
    except ValidationError as error:
        raise ApiError.INVALID_REQUEST('request is malformed',
                                       error.json(indent=None))
    try:
        return _REQUESTS[base_request.method].parse_obj(base_request.dict())
    except KeyError:
        raise ApiError.METHOD_NOT_FOUND('request method not found',
                                        None, base_request.id)
    except ValidationError as error:
        raise ApiError.INVALID_PARAMS('request params are invalid',
                                      error.json(indent=None), base_request.id)
