from __future__ import annotations

import sys

from . import _import_wrapper
from ._version import __version__ as __version__

if not getattr(sys, 'frozen', False):
    __getattr__ = _import_wrapper.__getattr__
