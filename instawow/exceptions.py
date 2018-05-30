
class ManagerResult:

    def __call__(self):
        return self


class PkgInstalled(ManagerResult):

    def __init__(self, pkg):
        super().__init__()
        self.new_pkg = pkg


class PkgUpdated(ManagerResult):

    def __init__(self, pkgs):
        super().__init__()
        self.old_pkg, self.new_pkg = pkgs


class PkgModified(ManagerResult):

    def __init__(self, key, value):
        super().__init__()
        self.key = key
        self.value = value


class PkgRemoved(ManagerResult):

    def __init__(self, pkg):
        super().__init__()
        self.old_pkg = pkg


class ManagerError(ManagerResult,
                   Exception):
    pass


class PkgAlreadyInstalled(ManagerError):
    pass


class PkgConflictsWithInstalled(ManagerError):

    def __init__(self, pkg):
        super().__init__()
        self.conflicting_pkg = pkg


class PkgConflictsWithPreexisting(ManagerError):
    pass


class PkgNonexistent(ManagerError):
    pass


class PkgNotInstalled(ManagerError):
    pass


class PkgOriginInvalid(ManagerError):

    def __init__(self, origin):
        super().__init__()
        self.origin = origin


class PkgUpToDate(ManagerError):
    pass


class CacheObsolete(ManagerError):
    pass


class InternalError(ManagerResult,
                    Exception):

    def __init__(self, error):
        super().__init__()
        self.error = error
