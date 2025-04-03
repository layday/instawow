from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

import attrs
import cattrs
import cattrs.gen
import cattrs.preconf.json

_missing = object()


class FieldMetadata(TypedDict, total=False):
    env: str
    preparse_from_env: bool
    store: bool


class UninitialisedConfigError(Exception):
    pass


def ensure_dirs(dirs: Iterable[Path]) -> None:
    for dir_ in dirs:
        dir_.mkdir(exist_ok=True, parents=True)


def make_config_converter() -> cattrs.Converter:
    converter = cattrs.Converter()
    cattrs.preconf.json.configure_converter(converter)
    converter.register_structure_hook(Path, lambda v, _: Path(v))
    converter.register_unstructure_hook(Path, str)
    return converter


@lru_cache(1)
def _make_write_converter():
    converter = make_config_converter()

    @converter.register_unstructure_hook_factory(attrs.has)
    def _[T](type_: type[T]):
        return cattrs.gen.make_dict_unstructure_fn(
            type_,
            converter,
            **{  # pyright: ignore[reportArgumentType]  # See microsoft/pyright#5255
                f.name: cattrs.gen.override(omit=True)
                for f in attrs.fields(type_)
                if not f.metadata.get('store')
            },
        )

    return converter


def write_config(config: object, config_path: Path) -> None:
    converter = _make_write_converter()
    config_path.write_text(
        json.dumps(converter.unstructure(config), indent=2),
        encoding='utf-8',
    )


def read_config(config_cls: type, config_path: Path, missing_ok: bool = False) -> dict[str, Any]:
    try:
        values = json.loads(config_path.read_bytes())
        for field in attrs.fields(config_cls):
            if attrs.has(field.type):
                maybe_values = read_config(
                    field.type, config_path.with_stem(f'{config_path.stem}.{field.name}'), True
                )
                if maybe_values:
                    values |= {field.name: maybe_values}

    except FileNotFoundError:
        if missing_ok:
            return {}
        raise UninitialisedConfigError from None
    else:
        return values


def _compute_var(field: attrs.Attribute[object], default: object):
    env = field.metadata.get('env')
    if not env:
        return default

    value = os.environ.get(f'{env}_{field.name}'.upper())
    if value is None:
        return default
    elif field.metadata.get('preparse_from_env'):
        return json.loads(value)
    else:
        return value


def read_env_vars(config_cls: type, values: Mapping[str, object]) -> dict[str, object]:
    return {
        f.name: v
        for f in attrs.fields(config_cls)
        for v in (_compute_var(f, values.get(f.name, _missing)),)
        if v is not _missing
    }


config_converter = make_config_converter()


@config_converter.register_structure_hook_factory(attrs.has)
def _(type_: type[Any]):
    "Allow passing in a structured attrs instance to ``structure``."
    structure = config_converter.gen_structure_attrs_fromdict(type_)

    def structure_wrapper(value: Mapping[str, Any], type_: type[Any]):
        return value if isinstance(value, type_) else structure(value, type_)

    return structure_wrapper
