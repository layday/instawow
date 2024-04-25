from __future__ import annotations

import sys
from functools import partial
from typing import TYPE_CHECKING, Any

import attrs

if sys.version_info >= (3, 11):
    from enum import StrEnum as StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        @staticmethod
        def _generate_next_value_(name: str, start: int, count: int, last_values: list[object]):
            return name.lower()


def add_exc_note(exc: BaseException, note: str) -> None:
    if sys.version_info >= (3, 11):
        exc.add_note(note)

    else:
        exc_without_notes: Any = exc

        if not hasattr(exc, '__notes__'):
            exc_without_notes.__notes__ = list[str]()
        exc_without_notes.__notes__.append(note)


if TYPE_CHECKING:
    fauxfrozen = attrs.frozen
else:
    fauxfrozen = partial(attrs.define, unsafe_hash=True)
