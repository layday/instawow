from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import types


def __getattr__(name: str) -> types.ModuleType:
    """Defer importing own modules until attempting to access an attribute.

    Importing this in ``__init__`` will overwrite relative imports.
    """
    fullname = __package__ + '.' + name
    try:
        return sys.modules[fullname]
    except KeyError:
        # ``module_from_spec`` will raise if the spec is ``None`` but this is
        # converted to an ``ImportError`` by Python's import mechanism so we
        # don't have to be too fussy about what returns which - everything's
        # gonna work out just fine, I promise
        spec: Any = importlib.util.find_spec(fullname)
        sys.modules[fullname] = module = importlib.util.module_from_spec(spec)
        lazy_loader = importlib.util.LazyLoader(spec.loader)
        lazy_loader.exec_module(module)
        return module
