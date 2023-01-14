from __future__ import annotations

from collections.abc import Collection
from typing import Any, Final, Protocol

from attrs import asdict

from . import models
from .common import Strategy, StrategyValues


class ManagerResult(Protocol):
    @property
    def message(self) -> str:
        ...


class _SuccessResult:
    status: Final = 'success'


class PkgInstalled(ManagerResult, _SuccessResult):
    def __init__(self, pkg: models.Pkg) -> None:
        super().__init__()
        self.pkg = pkg

    @property
    def message(self) -> str:
        return f'installed {self.pkg.version}'


class PkgUpdated(ManagerResult, _SuccessResult):
    def __init__(self, old_pkg: models.Pkg, new_pkg: models.Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg

    @property
    def message(self) -> str:
        return f'updated {self.old_pkg.version} to {self.new_pkg.version}'


class PkgRemoved(ManagerResult, _SuccessResult):
    def __init__(self, old_pkg: models.Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg

    @property
    def message(self) -> str:
        return 'removed'


class ManagerError(ManagerResult, Exception):
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
    def __init__(self, folders: set[str]) -> None:
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
    def __init__(self, strategies: StrategyValues) -> None:
        super().__init__()
        self._strategies = strategies

    @property
    def message(self) -> str:
        return 'no files found for: ' + '; '.join(
            f'{s}={v!r}' for s, v in asdict(self._strategies).items()
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
        return f'strategies are not valid for source: {", ".join(self.strategies)}'


class InternalError(Exception, ManagerResult):
    status: Final = 'error'

    @property
    def message(self) -> str:
        return f'internal error: "{self.args[0]}"'
