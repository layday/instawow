from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Optional, Sequence, Set

if TYPE_CHECKING:
    from .models import Pkg
    from .resolvers import Strategies


class ManagerResult:
    format_message: ClassVar[str]

    @property
    def message(self) -> str:
        return self.format_message.format(self=self)


class PkgInstalled(ManagerResult):
    format_message = 'installed {self.pkg.version}'

    def __init__(self, pkg: Pkg) -> None:
        super().__init__()
        self.pkg = pkg


class PkgUpdated(ManagerResult):
    format_message = 'updated {self.old_pkg.version} to {self.new_pkg.version}'

    def __init__(self, old_pkg: Pkg, new_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg


class PkgRemoved(ManagerResult):
    format_message = 'removed'

    def __init__(self, old_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg


class ManagerError(ManagerResult, Exception):
    pass


class PkgAlreadyInstalled(ManagerError):
    format_message = 'package already installed'


class PkgConflictsWithInstalled(ManagerError):
    format_message = 'package folders conflict with installed package {self.conflicts[0]}'

    def __init__(self, conflicts: Sequence[Pkg]) -> None:
        from .resolvers import Defn

        super().__init__()
        self.conflicts = [Defn.from_pkg(c) for c in conflicts]


class PkgConflictsWithForeign(ManagerError):
    format_message = 'package folders conflict with {self.folders}'

    def __init__(self, folders: Set[str]) -> None:
        super().__init__()
        self.folders = ', '.join(f"'{f}'" for f in folders)


class PkgNonexistent(ManagerError):
    format_message = 'package does not exist'


class PkgFileUnavailable(ManagerError):
    format_message = 'package file is not available for download'

    def __init__(self, specialised_message: Optional[str] = None) -> None:
        super().__init__()
        self.specialised_message = specialised_message

    @property
    def message(self) -> str:
        return self.specialised_message or super().message


class PkgNotInstalled(ManagerError):
    format_message = 'package is not installed'


class PkgSourceInvalid(ManagerError):
    format_message = 'package source is invalid'


class PkgUpToDate(ManagerError):
    format_message = 'package is up to date'


class PkgStrategyUnsupported(ManagerError):
    format_message = '{self.strategy.name!r} strategy is not valid for source'

    def __init__(self, strategy: Strategies) -> None:
        super().__init__()
        self.strategy = strategy


class InternalError(ManagerResult, Exception):
    format_message = 'internal error'

    def __init__(self, error: BaseException, stringify_error: bool = False) -> None:
        super().__init__()
        self.error = error
        self.stringify_error = stringify_error

    @property
    def message(self) -> str:
        return (
            f'{self.format_message}: "{self.error}"' if self.stringify_error else super().message
        )
