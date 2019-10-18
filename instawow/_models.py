from typing import Any


def __getattr__(name: str) -> Any:
    "Lazy-load SQLAlchemy models."
    from . import models

    return getattr(models, name)
