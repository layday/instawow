from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Sequence, Optional, Set

if TYPE_CHECKING:
    from .models import Pkg


class ManagerResult:

    fmt_message: ClassVar[str]

    def __call__(self) -> ManagerResult:
        return self

    @property
    def message(self) -> str:
        return self.fmt_message.format(self=self)


class PkgInstalled(ManagerResult):

    fmt_message = 'installed {self.new_pkg.version}'

    def __init__(self, new_pkg: Pkg) -> None:
        super().__init__()
        self.new_pkg = new_pkg


class PkgUpdated(ManagerResult):

    fmt_message = 'updated {self.old_pkg.version} to {self.new_pkg.version}'

    def __init__(self, old_pkg: Pkg, new_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg


class PkgRemoved(ManagerResult):

    fmt_message = 'removed'

    def __init__(self, old_pkg: Pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg


class ManagerError(ManagerResult,
                   Exception):
    pass


class PkgAlreadyInstalled(ManagerError):

    fmt_message = 'package already installed'


class PkgConflictsWithInstalled(ManagerError):

    fmt_message = "package folders conflict with installed package's "\
                  '{self.conflicts[0].origin}:{self.conflicts[0].slug}'

    def __init__(self, conflicts: Sequence[Pkg]) -> None:
        super().__init__()
        self.conflicts = conflicts


class PkgConflictsWithUncontrolled(ManagerError):

    fmt_message = "package folders conflict with an add-on's"\
                  ' not controlled by instawow'

    def __init__(self, folders: Set[str]) -> None:
        super().__init__()
        self.folders = folders


class PkgNonexistent(ManagerError):

    fmt_message = 'package does not exist'


class PkgFileUnavailable(ManagerError):

    fmt_message = 'package file is not available for download'

    def __init__(self, detailed_message: Optional[str] = None) -> None:
        super().__init__()
        self.detailed_message = detailed_message

    @property
    def message(self) -> str:
        return self.detailed_message or super().message


class PkgNotInstalled(ManagerError):

    fmt_message = 'package is not installed'


class PkgOriginInvalid(ManagerError):

    fmt_message = 'package source is invalid'


class PkgUpToDate(ManagerError):

    fmt_message = 'package is up to date'


class PkgStrategyUnsupported(ManagerError):

    fmt_message = 'strategy {self.strategy!r} is not valid for source'

    def __init__(self, strategy: str) -> None:
        super().__init__()
        self.strategy = strategy


class InternalError(ManagerResult,
                    Exception):

    fmt_message = 'instawow encountered an error'

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error
