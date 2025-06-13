from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import lru_cache, partial
from typing import TYPE_CHECKING

import attrs

type _Validator[T] = Callable[[object, attrs.Attribute[T], T], None]


fauxfrozen = attrs.frozen if TYPE_CHECKING else partial(attrs.define, unsafe_hash=True)


def enrich_validator_exc[T](validator: _Validator[T]) -> _Validator[T]:
    "Pretend validation error originates from cattrs for uniformity with structural errors."

    import cattrs

    def wrapper(model: object, attr: attrs.Attribute[T], value: T):
        try:
            validator(model, attr, value)
        except BaseException as exc:
            note = f'Structuring class {model.__class__.__name__} @ attribute {attr.name}'
            exc.add_note(cattrs.AttributeValidationNote(note, attr.name, attr.type))
            raise

    return wrapper


@fauxfrozen
class EvolveIdent:
    value: object


def evolve[T](attrs_instance: T, changes: Mapping[str, object | EvolveIdent]) -> T:
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


@lru_cache(1)
def simple_converter():
    from cattrs import Converter

    return Converter()
