
from __future__ import annotations

__all__ = ('ErrorCodes',
           'ApiError',
           'ResolveRequest',
           'InstallRequest',
           'UpdateRequest',
           'RemoveRequest',
           'GetRequest',
           'SuccessResponse',
           'ErrorResponse',
           'jsonify',
           'parse_request')

import abc
from datetime import datetime
from enum import Enum, IntEnum
from functools import partial
from json import JSONDecodeError, JSONEncoder, loads as json_loads
from pathlib import Path
from typing import Any, Awaitable, Callable, Generator, List, Optional, Tuple, Union

from pydantic import BaseModel, StrictStr, ValidationError
from pydantic.errors import IntegerError

from .config import Config
from .manager import WsManager
from .models import (Pkg, PkgFolder, PkgOptions,
                     PkgCoercer, PkgFolderCoercer, PkgOptionsCoercer)
from .resolvers import Strategies
from .utils import setup_logging

try:
    from typing import Literal      # type: ignore
except ImportError:
    from typing_extensions import Literal


JSONRPC_VERSION = '2.0'
API_VERSION = '0'


class ErrorCodes(IntEnum):

    PARSE_ERROR                     = -32700
    INVALID_REQUEST                 = -32600
    METHOD_NOT_FOUND                = -32601
    INVALID_PARAMS                  = -32602
    INTERNAL_ERROR                  = -32603

    MANAGER_ERROR                   = +10000
    CONFIG_ERROR                    = +10010
    PKG_ALREADY_INSTALLED           = +10021
    PKG_CONFLICTS_WITH_INSTALLED    = +10022
    PKG_CONFLICTS_WITH_UNCONTROLLED = +10023
    PKG_NONEXISTENT                 = +10024
    PKG_TEMPORARILY_UNAVAILABLE     = +10025
    PKG_NOT_INSTALLED               = +10026
    PKG_ORIGIN_INVALID              = +10027
    PKG_UP_TO_DATE                  = +10028
    PKG_STRATEGY_INVALID            = +10029

    ManagerError                    = +10000
    ConfigError                     = +10010
    PkgAlreadyInstalled             = +10021
    PkgConflictsWithInstalled       = +10022
    PkgConflictsWithUncontrolled    = +10023
    PkgNonexistent                  = +10024
    PkgTemporarilyUnavailable       = +10025
    PkgNotInstalled                 = +10026
    PkgOriginInvalid                = +10027
    PkgUpToDate                     = +10028
    PkgStrategyInvalid              = +10029


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


def split_uri(manager: WsManager, uri: str) -> Tuple[str, str]:
    "Turn a URI into a source and slug pair."
    resolvers = manager.resolvers.values()
    try:
        return next(filter(None, (r.decompose_url(uri) for r in resolvers)))
    except StopIteration:
        return uri.partition(':')[::2]


class Message(BaseModel,
              abc.ABC):

    jsonrpc: Literal['2.0']


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

    id: Union[StrictInt, StrictStr]
    method: str
    params: RequestParams

    def prepare_response(self, manager: WsManager) -> Awaitable:
        raise NotImplementedError

    def consume_result(self, result: Any) -> SuccessResponse:
        raise NotImplementedError


class SetupRequestParams(RequestParams):

    addon_dir: Path
    game_flavour: Literal['retail', 'classic']


class SetupRequest(Request):

    method: Literal['setup']
    params: SetupRequestParams

    def prepare_response(self, manager: WsManager) -> Awaitable:
        async def setup() -> Config:
            config = Config(**dict(self.params)).write()
            setup_logging(config)
            manager.finalise(config)
            return config

        return setup()

    def consume_result(self, result: Config) -> SuccessResponse:
        return SuccessResponse(result={'config': json_loads(result.json())}, id=self.id)


class ResolveRequestParams(RequestParams):

    uris: List[str]
    resolution_strategy: Strategies

    class Config:
        use_enum_values = True


class ResolveRequest(Request):

    method: Literal['resolve']
    params: ResolveRequestParams

    def prepare_response(self, manager: WsManager) -> Awaitable:
        return manager.resolve([split_uri(manager, u) for u in self.params.uris],
                               self.params.resolution_strategy)

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=list(result.values()), id=self.id)


class InstallRequestParams(RequestParams):

    uris: List[str]
    resolution_strategy: Strategies
    replace: bool

    class Config:
        use_enum_values = True


class InstallRequest(Request):

    method: Literal['install']
    params: InstallRequestParams

    def prepare_response(self, manager: WsManager) -> Awaitable:
        return manager.prep_install([split_uri(manager, u) for u in self.params.uris],
                                    self.params.resolution_strategy,
                                    self.params.replace)

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=result.new_pkg, id=self.id)


class UpdateRequestParams(RequestParams):

    uris: List[str]


class UpdateRequest(Request):

    method: Literal['update']
    params: UpdateRequestParams

    def prepare_response(self, manager: WsManager) -> Awaitable:
        return manager.prep_update([split_uri(manager, u) for u in self.params.uris])

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=result.new_pkg, id=self.id)


class RemoveRequestParams(RequestParams):

    uris: List[str]


class RemoveRequest(Request):

    method: Literal['remove']
    params: RemoveRequestParams

    def prepare_response(self, manager: WsManager) -> Awaitable:
        return manager.prep_remove([split_uri(manager, u) for u in self.params.uris])

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=None, id=self.id)


class GetRequestParams(RequestParams):

    uris: List[str]


class GetRequest(Request):

    method: Literal['get']
    params: GetRequestParams

    def prepare_response(self, manager: WsManager) -> Awaitable:
        async def get() -> list:
            if self.params.uris:
                return [manager.get(*split_uri(manager, u)) for u in self.params.uris]
            else:
                return manager.db.query(Pkg).all()

        return get()

    def consume_result(self, result: Any) -> SuccessResponse:
        return SuccessResponse(result=result, id=self.id)


class Response(Message,
               abc.ABC):

    jsonrpc = '2.0'
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


class _PkgConverter(PkgCoercer):

    folders: List[PkgFolderCoercer]
    options: PkgOptionsCoercer


_CONVERTERS = [(Pkg, lambda v: _PkgConverter.from_orm(v).dict()),
               (Message, Message.dict),
               (Path, str),
               (datetime, datetime.isoformat),]


class Encoder(JSONEncoder):

    def default(self, value: Any) -> Any:
        try:
            return next(c(value) for t, c in _CONVERTERS if isinstance(value, t))
        except StopIteration:
            return super().default(value)


jsonify = Encoder().encode


_methods = {'setup': SetupRequest,
            'resolve': ResolveRequest,
            'install': InstallRequest,
            'update': UpdateRequest,
            'remove': RemoveRequest,
            'get': GetRequest,}


def parse_request(message: str) -> Request:
    "Parse a JSON string into a sub-``Request`` object."
    try:
        data = json_loads(message)
    except JSONDecodeError as error:
        raise ApiError.PARSE_ERROR('request is not valid JSON', str(error))
    try:
        Request(**data)
    except TypeError as error:
        raise ApiError.INVALID_REQUEST('request is malformed',
                                       *error.args, None)
    except ValidationError as error:
        raise ApiError.INVALID_REQUEST('request is malformed',
                                       error.json(indent=None),
                                       getattr(data, 'get', lambda _: None)('id'))

    cls = _methods.get(data['method'])
    if cls:
        try:
            return cls(**data)
        except ValidationError as error:
            raise ApiError.INVALID_PARAMS('request params are invalid',
                                          error.json(indent=None), data.get('id'))
    else:
        raise ApiError.METHOD_NOT_FOUND('request method not found',
                                        None, data.get('id'))
