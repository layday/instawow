from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, Sequence, Set

if TYPE_CHECKING:
    from .models import Pkg
    from .resolvers import Strategy


class ManagerResult:
    status: ClassVar[str]
    message_template: ClassVar[str]

    @property
    def message(self) -> str:
        return self.message_template.format(self=self)


class PkgInstalled(ManagerResult):
    status = 'success'
    message_template = 'installed {self.pkg.version}'

    def __init__(self, pkg: Pkg) -> None:
        super().__init__()
        self.pkg = pkg


class PkgUpdated(ManagerResult):
    status = 'success'
    message_template = 'updated {self.old_pkg.version} to {self.new_pkg.version}'

    def __init__(self, old_pkg: Pkg, new_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg


class PkgRemoved(ManagerResult):
    status = 'success'
    message_template = 'removed'

    def __init__(self, old_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg


class ManagerError(ManagerResult, Exception):
    status = 'failure'


class PkgAlreadyInstalled(ManagerError):
    message_template = 'package already installed'


class PkgConflictsWithInstalled(ManagerError):
    def __init__(self, conflicting_pkgs: Sequence[Pkg]) -> None:
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
    message_template = 'package does not exist'


class PkgFileUnavailable(ManagerError):
    message_template = 'package file is not available for download'

    def __init__(self, custom_message: Optional[str] = None) -> None:
        super().__init__()
        self._custom_message = custom_message

    @property
    def message(self) -> str:
        return self._custom_message or super().message


class PkgNotInstalled(ManagerError):
    message_template = 'package is not installed'


class PkgSourceInvalid(ManagerError):
    message_template = 'package source is invalid'


class PkgUpToDate(ManagerError):
    def __init__(self, is_pinned: bool) -> None:
        super().__init__()
        self.is_pinned = is_pinned

    @property
    def message(self) -> str:
        return f'package is {"pinned" if self.is_pinned else "up to date"}'


class PkgStrategyUnsupported(ManagerError):
    message_template = '{self.strategy.name!r} strategy is not valid for source'

    def __init__(self, strategy: Strategy) -> None:
        super().__init__()
        self.strategy = strategy


class InternalError(ManagerResult, Exception):
    status = 'error'

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    @property
    def message(self) -> str:
        return f'internal error: "{self.error}"'
