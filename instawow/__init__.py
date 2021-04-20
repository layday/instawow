from . import _import_wrapper
from ._version import __version__

__getattr__ = _import_wrapper.__getattr__

DB_REVISION = '764fa963cc71'
