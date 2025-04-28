from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Collection, Set
from functools import wraps
from typing import Literal, LiteralString, Protocol, TypedDict, overload

from typing_extensions import TypeIs

from .definitions import Strategies, Strategy
from .pkg_db import models as pkg_models


class Result[StatusT: LiteralString](Protocol):  # pragma: no cover
    status: StatusT

    def __str__(self) -> str: ...


class _SuccessResult(Result[Literal['success']]):
    status = 'success'


class PkgInstalled(_SuccessResult):
    def __init__(self, pkg: pkg_models.Pkg, *, dry_run: bool = False) -> None:
        super().__init__()
        self.pkg = pkg
        self.dry_run = dry_run

    def __str__(self) -> str:
        return f'{"would have installed" if self.dry_run else "installed"} {self.pkg.version}'


class PkgUpdated(_SuccessResult):
    def __init__(
        self, old_pkg: pkg_models.Pkg, new_pkg: pkg_models.Pkg, *, dry_run: bool = False
    ) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg
        self.dry_run = dry_run

    def __str__(self) -> str:
        message = (
            f'{"would have updated" if self.dry_run else "updated"}'
            f' {self.old_pkg.version} to {self.new_pkg.version}'
        )

        if self.old_pkg.slug != self.new_pkg.slug:
            message += f' with new slug {self.new_pkg.slug!r}'

        if self.old_pkg.options != self.new_pkg.options:
            old_strategies = self.old_pkg.to_defn().strategies
            new_strategies = self.new_pkg.to_defn().strategies
            message += ' with new strategies: '
            message += '; '.join(
                f'{s}={v!r}' for s, v in new_strategies.items() - old_strategies.items()
            )

        return message


class PkgRemoved(_SuccessResult):
    def __init__(self, old_pkg: pkg_models.Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg

    def __str__(self) -> str:
        return 'removed'


class ManagerError(Result[Literal['failure']], Exception):
    status = 'failure'

    def __str__(self) -> str:
        raise NotImplementedError


class PkgAlreadyInstalled(ManagerError):
    def __str__(self) -> str:
        return 'package already installed'


class PkgConflictsWithInstalled(ManagerError):
    def __init__(
        self, conflicting_pkgs: Collection[TypedDict[{'source': str, 'id': str, 'name': str}]]
    ) -> None:
        super().__init__()
        self.conflicting_pkgs = conflicting_pkgs

    def __str__(self) -> str:
        return (
            'package folders conflict with installed package'
            + ('s ' if len(self.conflicting_pkgs) > 1 else ' ')
            + ', '.join(f'{c["name"]} ({c["source"]}:{c["id"]})' for c in self.conflicting_pkgs)
        )


class PkgConflictsWithUnreconciled(ManagerError):
    def __init__(self, folders: Set[str]) -> None:
        super().__init__()
        self.folders = folders

    def __str__(self) -> str:
        folders = ', '.join(f"'{f}'" for f in self.folders)
        return f'package folders conflict with {folders}'


class PkgNonexistent(ManagerError):
    def __str__(self) -> str:
        return 'package does not exist'


class PkgFilesMissing(ManagerError):
    def __init__(self, reason: str = 'no files are available for download') -> None:
        super().__init__()
        self._reason = reason

    def __str__(self) -> str:
        return self._reason


class PkgFilesNotMatching(ManagerError):
    def __init__(self, strategies: Strategies) -> None:
        super().__init__()
        self.strategies = strategies

    def __str__(self) -> str:
        return 'no files found for: ' + '; '.join(f'{s}={v!r}' for s, v in self.strategies.items())


class PkgNotInstalled(ManagerError):
    def __str__(self) -> str:
        return 'package is not installed'


class PkgSourceInvalid(ManagerError):
    def __str__(self) -> str:
        return 'package source is invalid'


class PkgSourceDisabled(ManagerError):
    def __init__(self, reason: str | None = None) -> None:
        super().__init__()
        self._reason = reason

    def __str__(self) -> str:
        return f'package source is disabled{f": {self._reason}" if self._reason else ""}'


class PkgUpToDate(ManagerError):
    def __init__(self, is_pinned: bool) -> None:
        super().__init__()
        self.is_pinned = is_pinned

    def __str__(self) -> str:
        return f'package is {"pinned" if self.is_pinned else "up to date"}'


class PkgStrategiesUnsupported(ManagerError):
    def __init__(self, strategies: Collection[Strategy]) -> None:
        super().__init__()
        self.strategies = strategies

    def __str__(self) -> str:
        return f'strategies are not valid for source: {", ".join(sorted(self.strategies))}'


class InternalError(Result[Literal['error']], Exception):
    status = 'error'

    def __str__(self) -> str:
        return f'internal error: "{self.args[0]}"'


type AnyResult[T] = T | ManagerError | InternalError


def _handle_internal_error(error: BaseException):
    from ._logging import logger

    traceback = error.__traceback__
    if traceback is not None:
        error = error.with_traceback(traceback.tb_next)

    logger.opt(
        exception=error,
    ).error('Unclassed error')

    return InternalError(error)


@overload
def resultify[**P, T](fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[AnyResult[T]]]: ...
@overload
def resultify[**P, T](fn: Callable[P, T]) -> Callable[P, AnyResult[T]]: ...


def resultify[**P](fn: Callable[P, object]):  # pyright: ignore[reportInconsistentOverload]
    "Capture raw errors and wrap them around ``InternalError``."

    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs):
            try:
                return await fn(*args, **kwargs)

            except (ManagerError, InternalError) as exception:
                return exception

            except BaseException as error:
                return _handle_internal_error(error)

        return async_wrapper

    else:

        @wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs):
            try:
                return fn(*args, **kwargs)

            except (ManagerError, InternalError) as exception:
                return exception

            except BaseException as error:
                return _handle_internal_error(error)

        return sync_wrapper


def is_error_result(result: AnyResult[object]) -> TypeIs[ManagerError | InternalError]:
    return isinstance(result, (ManagerError, InternalError))
