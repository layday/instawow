from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, Sequence, Set

if TYPE_CHECKING:
    from .models import Pkg
    from .resolvers import Strategy


class ManagerResult:
    kind: ClassVar[str]
    message_template: ClassVar[str]

    @property
    def message(self) -> str:
        return self.message_template.format(self=self)


class PkgInstalled(ManagerResult):
    kind = 'success'
    message_template = 'installed {self.pkg.version}'

    def __init__(self, pkg: Pkg) -> None:
        super().__init__()
        self.pkg = pkg


class PkgUpdated(ManagerResult):
    kind = 'success'
    message_template = 'updated {self.old_pkg.version} to {self.new_pkg.version}'

    def __init__(self, old_pkg: Pkg, new_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg


class PkgRemoved(ManagerResult):
    kind = 'success'
    message_template = 'removed'

    def __init__(self, old_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg


class ManagerError(ManagerResult, Exception):
    kind = 'failure'


class PkgAlreadyInstalled(ManagerError):
    message_template = 'package already installed'


class PkgConflictsWithInstalled(ManagerError):
    message_template = 'package folders conflict with installed package'

    def __init__(self, conflicting_pkgs: Sequence[Pkg]) -> None:
        super().__init__()
        self.conflicting_pkgs = conflicting_pkgs

    @property
    def message(self) -> str:
        return (
            self.message_template
            + ('s ' if len(self.conflicting_pkgs) > 1 else ' ')
            + ', '.join(f'{c.name} ({c.source}:{c.id})' for c in self.conflicting_pkgs)
        )


class PkgConflictsWithUnreconciled(ManagerError):
    message_template = 'package folders conflict with {self.folders}'

    def __init__(self, folders: Set[str]) -> None:
        super().__init__()
        self.folders = ', '.join(f"'{f}'" for f in folders)


class PkgNonexistent(ManagerError):
    message_template = 'package does not exist'


class PkgFileUnavailable(ManagerError):
    message_template = 'package file is not available for download'

    def __init__(self, message: Optional[str] = None) -> None:
        super().__init__()
        self._message = message

    @property
    def message(self) -> str:
        return self._message or super().message


class PkgNotInstalled(ManagerError):
    message_template = 'package is not installed'


class PkgSourceInvalid(ManagerError):
    message_template = 'package source is invalid'


class PkgUpToDate(ManagerError):
    message_template = 'package is up to date'


class PkgStrategyUnsupported(ManagerError):
    message_template = '{self.strategy.name!r} strategy is not valid for source'

    def __init__(self, strategy: Strategy) -> None:
        super().__init__()
        self.strategy = strategy


class InternalError(ManagerResult, Exception):
    kind = 'error'
    message_template = 'internal error'

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    @property
    def message(self) -> str:
        return f'{self.message_template}: "{self.error}"'
