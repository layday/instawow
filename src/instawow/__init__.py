from __future__ import annotations

import sys

from . import _import_wrapper

if not getattr(sys, 'frozen', False):
    __getattr__ = _import_wrapper.__getattr__

from ._version import __version__ as __version__
