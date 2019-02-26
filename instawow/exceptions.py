
from __future__ import annotations

from typing import ClassVar


__all__ = ('ManagerResult',
           'PkgInstalled',
           'PkgUpdated',
           'PkgRemoved',
           'ManagerError',
           'PkgAlreadyInstalled',
           'PkgConflictsWithInstalled',
           'PkgConflictsWithPreexisting',
           'PkgNonexistent',
           'PkgTemporarilyUnavailable',
           'PkgNotInstalled',
           'PkgOriginInvalid',
           'PkgUpToDate',
           'InternalError')


class ManagerResult:

    fmt_message: ClassVar[str]

    def __call__(self) -> ManagerResult:
        return self

    @property
    def message(self) -> str:
        return self.fmt_message.format(self=self)


class PkgInstalled(ManagerResult):

    fmt_message = 'installed {self.new_pkg.version} '\
                  'from {self.new_pkg.options.strategy}'

    def __init__(self, new_pkg) -> None:
        super().__init__()
        self.new_pkg = new_pkg


class PkgUpdated(ManagerResult):

    fmt_message = 'updated {self.old_pkg.version} to {self.new_pkg.version} '\
                  'from {self.new_pkg.options.strategy}'

    def __init__(self, old_pkg, new_pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg


class PkgRemoved(ManagerResult):

    fmt_message = 'removed'

    def __init__(self, old_pkg) -> None:
        super().__init__()
        self.old_pkg = old_pkg


class ManagerError(ManagerResult,
                   Exception):
    pass


class PkgAlreadyInstalled(ManagerError):

    fmt_message = 'package already installed'


class PkgConflictsWithInstalled(ManagerError):

    fmt_message = "package folders conflict with installed package's "\
                  '{self.conflicting_pkg.origin}:{self.conflicting_pkg.slug}'

    def __init__(self, conflicting_pkg) -> None:
        super().__init__()
        self.conflicting_pkg = conflicting_pkg


class PkgConflictsWithPreexisting(ManagerError):

    fmt_message = "package folders conflict with an add-on's"\
                  ' not installed by instawow'

    def __init__(self, folders) -> None:
        super().__init__()
        self.folders = folders


class PkgNonexistent(ManagerError):

    fmt_message = 'package does not exist'


class PkgTemporarilyUnavailable(ManagerError):

    fmt_message = 'package is temporarily unavailable'


class PkgNotInstalled(ManagerError):

    fmt_message = 'package is not installed'


class PkgOriginInvalid(ManagerError):

    fmt_message = 'package origin is invalid'


class PkgUpToDate(ManagerError):

    fmt_message = 'package is up to date'


class InternalError(ManagerResult,
                    Exception):

    fmt_message = 'encountered {self.error.__class__.__name__}'

    def __init__(self, error) -> None:
        super().__init__()
        self.error = error
