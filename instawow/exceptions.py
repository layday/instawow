from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, ClassVar, Optional, Sequence, Set

from loguru import logger

if TYPE_CHECKING:
    from .models import Pkg
    from .resolvers import Strategies


class ManagerResult:
    fmt_message: ClassVar[str]

    @property
    def message(self) -> str:
        return self.fmt_message.format(self=self)

    @staticmethod
    async def acapture(awaitable: Awaitable[ManagerResult]) -> ManagerResult:
        "Capture errors in coroutines."
        try:
            return await awaitable
        except ManagerError as error:
            return error
        except Exception as error:
            logger.exception('error!')
            return InternalError(error)


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


class ManagerError(ManagerResult, Exception):
    pass


class PkgAlreadyInstalled(ManagerError):
    fmt_message = 'package already installed'


class PkgConflictsWithInstalled(ManagerError):
    fmt_message = 'package folders conflict with installed package {self.conflicts[0]}'

    def __init__(self, conflicts: Sequence[Pkg]) -> None:
        from .resolvers import Defn

        super().__init__()
        self.conflicts = [Defn.from_pkg(c) for c in conflicts]


class PkgConflictsWithForeign(ManagerError):
    fmt_message = 'package folders conflict with {self.folders}'

    def __init__(self, folders: Set[str]) -> None:
        super().__init__()
        self.folders = ', '.join(f"'{f}'" for f in folders)


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


class PkgSourceInvalid(ManagerError):
    fmt_message = 'package source is invalid'


class PkgUpToDate(ManagerError):
    fmt_message = 'package is up to date'


class PkgStrategyUnsupported(ManagerError):
    fmt_message = '{self.strategy.name!r} strategy is not valid for source'

    def __init__(self, strategy: Strategies) -> None:
        super().__init__()
        self.strategy = strategy


class InternalError(ManagerResult, Exception):
    fmt_message = 'instawow encountered an error'

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error
