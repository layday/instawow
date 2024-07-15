from __future__ import annotations

from . import _import_wrapper

__getattr__ = _import_wrapper.__getattr__

from ._version_check import get_version

__version__ = get_version()
