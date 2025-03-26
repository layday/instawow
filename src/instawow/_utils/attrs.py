from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar

import attrs

_T = TypeVar('_T')

_Validator: TypeAlias = Callable[[object, 'attrs.Attribute[_T]', _T], None]


fauxfrozen = attrs.frozen if TYPE_CHECKING else partial(attrs.define, unsafe_hash=True)


def enrich_validator_exc(validator: _Validator[_T]) -> _Validator[_T]:
    "Pretend validation error originates from cattrs for uniformity with structural errors."

    import cattrs

    def wrapper(model: object, attr: attrs.Attribute[_T], value: _T):
        try:
            validator(model, attr, value)
        except BaseException as exc:
            note = f'Structuring class {model.__class__.__name__} @ attribute {attr.name}'
            exc.add_note(cattrs.AttributeValidationNote(note, attr.name, attr.type))
            raise

    return wrapper


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
