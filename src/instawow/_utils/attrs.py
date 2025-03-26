from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from typing import TYPE_CHECKING, Any, TypeVar

import attrs

_T = TypeVar('_T')


fauxfrozen = attrs.frozen if TYPE_CHECKING else partial(attrs.define, unsafe_hash=True)


@fauxfrozen
class EvolveIdent:
    value: Mapping[Any, Any]


def evolve(attrs_instance: _T, changes: Mapping[str, Any | EvolveIdent]) -> _T:
    return attrs.evolve(
        attrs_instance,
        **{
            k: evolve(
                getattr(attrs_instance, k),
                v,  # pyright: ignore[reportUnknownArgumentType]
            )
            if isinstance(v, Mapping)
            else v.value
            if isinstance(v, EvolveIdent)
            else v
            for k, v in changes.items()
        },
    )
