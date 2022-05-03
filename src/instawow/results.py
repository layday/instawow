from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from typing_extensions import Final, Protocol

from . import models
from .common import Strategy


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
    def __init__(self, conflicting_pkgs: Sequence[Any]) -> None:
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


class PkgFileUnavailable(ManagerError):
    def __init__(self, custom_message: str | None = None) -> None:
        super().__init__()
        self._custom_message = custom_message

    @property
    def message(self) -> str:
        return self._custom_message or 'package file is not available for download'


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


class PkgStrategyUnsupported(ManagerError):
    def __init__(self, strategy: Strategy) -> None:
        super().__init__()
        self.strategy = strategy

    @property
    def message(self) -> str:
        return f"'{self.strategy}' strategy is not valid for source"


class InternalError(Exception, ManagerResult):
    status: Final = 'error'

    @property
    def message(self) -> str:
        return f'internal error: "{self.args[0]}"'
