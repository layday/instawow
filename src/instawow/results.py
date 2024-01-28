from __future__ import annotations

from collections.abc import Awaitable, Collection, Set
from typing import Any, Final, Protocol, TypeAlias, TypeVar

from attrs import asdict
from loguru import logger

from . import pkg_models
from .common import Strategy, StrategyValues

_T = TypeVar('_T')

AnyResult: TypeAlias = '_T | ManagerError | InternalError'


class Result(Protocol):  # pragma: no cover
    @property
    def message(self) -> str:
        ...


class _SuccessResult:
    status: Final = 'success'


class PkgInstalled(Result, _SuccessResult):
    def __init__(self, pkg: pkg_models.Pkg, *, dry_run: bool = False) -> None:
        super().__init__()
        self.pkg = pkg
        self.dry_run = dry_run

    @property
    def message(self) -> str:
        return f'{"would have installed" if self.dry_run else "installed"} {self.pkg.version}'


class PkgUpdated(Result, _SuccessResult):
    def __init__(
        self, old_pkg: pkg_models.Pkg, new_pkg: pkg_models.Pkg, *, dry_run: bool = False
    ) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg
        self.dry_run = dry_run

    @property
    def message(self) -> str:
        message = (
            f'{"would have updated" if self.dry_run else "updated"}'
            f' {self.old_pkg.version} to {self.new_pkg.version}'
        )

        if self.old_pkg.slug != self.new_pkg.slug:
            message += f' with new slug {self.new_pkg.slug!r}'

        if self.old_pkg.options != self.new_pkg.options:
            old_strategies = asdict(self.old_pkg.to_defn().strategies)
            new_strategies = asdict(self.new_pkg.to_defn().strategies)
            message += ' with new strategies: '
            message += '; '.join(
                f'{s}={v!r}' for s, v in new_strategies.items() - old_strategies.items()
            )

        return message


class PkgRemoved(Result, _SuccessResult):
    def __init__(self, old_pkg: pkg_models.Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg

    @property
    def message(self) -> str:
        return 'removed'


class ManagerError(Result, Exception):
    status: Final = 'failure'

    @property
    def message(self) -> str:
        raise NotImplementedError


class PkgAlreadyInstalled(ManagerError):
    @property
    def message(self) -> str:
        return 'package already installed'


class PkgConflictsWithInstalled(ManagerError):
    def __init__(self, conflicting_pkgs: Collection[Any]) -> None:
        super().__init__()
        self.conflicting_pkgs = conflicting_pkgs

    @property
    def message(self) -> str:
        return (
            'package folders conflict with installed package'
            + ('s ' if len(self.conflicting_pkgs) > 1 else ' ')
            + ', '.join(f'{c.name} ({c.source}:{c.id})' for c in self.conflicting_pkgs)
        )


class PkgConflictsWithUnreconciled(ManagerError):
    def __init__(self, folders: Set[str]) -> None:
        super().__init__()
        self.folders = folders

    @property
    def message(self) -> str:
        folders = ', '.join(f"'{f}'" for f in self.folders)
        return f'package folders conflict with {folders}'


class PkgNonexistent(ManagerError):
    @property
    def message(self) -> str:
        return 'package does not exist'


class PkgFilesMissing(ManagerError):
    def __init__(self, custom_message: str | None = None) -> None:
        super().__init__()
        self._custom_message = custom_message

    @property
    def message(self) -> str:
        return self._custom_message or 'no files are available for download'


class PkgFilesNotMatching(ManagerError):
    def __init__(self, strategy_values: StrategyValues) -> None:
        super().__init__()
        self._strategy_values = strategy_values

    @property
    def message(self) -> str:
        return 'no files found for: ' + '; '.join(
            f'{s}={v!r}' for s, v in asdict(self._strategy_values).items()
        )


class PkgNotInstalled(ManagerError):
    @property
    def message(self) -> str:
        return 'package is not installed'


class PkgSourceInvalid(ManagerError):
    @property
    def message(self) -> str:
        return 'package source is invalid'


class PkgUpToDate(ManagerError):
    def __init__(self, is_pinned: bool) -> None:
        super().__init__()
        self.is_pinned = is_pinned

    @property
    def message(self) -> str:
        return f'package is {"pinned" if self.is_pinned else "up to date"}'


class PkgStrategiesUnsupported(ManagerError):
    def __init__(self, strategies: Collection[Strategy]) -> None:
        super().__init__()
        self.strategies = strategies

    @property
    def message(self) -> str:
        return f'strategies are not valid for source: {", ".join(sorted(self.strategies))}'


class InternalError(Result, Exception):
    status: Final = 'error'

    @property
    def message(self) -> str:
        return f'internal error: "{self.args[0]}"'


async def resultify_async_exc(
    awaitable: Awaitable[_T],
) -> AnyResult[_T]:
    "Capture and log an exception raised in a coroutine."
    try:
        return await awaitable
    except (ManagerError, InternalError) as error:
        return error
    except BaseException as error:
        logger.exception('unclassed error')
        return InternalError(error)
