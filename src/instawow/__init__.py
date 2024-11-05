from __future__ import annotations

from . import _import_wrapper

NAME = __spec__.parent

__getattr__ = _import_wrapper.make_getattr(NAME)
