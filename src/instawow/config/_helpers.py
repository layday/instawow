from __future__ import annotations

import json
import os
from collections.abc import Mapping
from functools import lru_cache, partial
from pathlib import Path
from typing import Any, Literal, NewType, TypedDict

import attrs
import cattrs
import cattrs.gen
import cattrs.preconf.json


class FieldMetadata(TypedDict, total=False):
    env_prefix: str | Literal[True]
    store: Literal[True, 'independently']
    store_alias: str


SecretStr = NewType('SecretStr', str)


class UninitialisedConfigError(Exception):
    pass


def ensure_dirs(*dirs: Path) -> None:
    for dir_ in dirs:
        dir_.mkdir(exist_ok=True, parents=True)


def make_config_converter() -> cattrs.Converter:
    converter = cattrs.Converter()
    cattrs.preconf.json.configure_converter(converter)
    converter.register_structure_hook(Path, lambda v, _: Path(v))
    converter.register_unstructure_hook(Path, str)
    return converter


@lru_cache(1)
def make_display_converter():
    import cattrs.gen

    converter = make_config_converter()

    @partial(converter.register_unstructure_hook, SecretStr)
    def _(value: SecretStr):
        return '*' * 10

    @converter.register_unstructure_hook_factory(attrs.has)
    def _[T](cls: type[T], converter: cattrs.Converter):
        return cattrs.gen.make_dict_unstructure_fn(cls, converter, _cattrs_include_init_false=True)

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


def read_config(attrs_cls: type, config_path: Path, missing_ok: bool = False) -> dict[str, Any]:
    try:
        values = json.loads(config_path.read_bytes())
        for field in attrs.fields(
            attrs.resolve_types(attrs_cls),
        ):
            if not field.init:
                continue

            metadata: FieldMetadata = field.metadata
            store = metadata.get('store')
            name = metadata.get('store_alias') or field.name

            if store == 'independently':
                maybe_values = read_config(
                    field.type, config_path.with_stem(f'{config_path.stem}.{name}'), True
                )
                if maybe_values:
                    values |= {field.name: maybe_values}
            elif name != field.name and name in values:
                values[field.name] = values[name]

    except FileNotFoundError:
        if missing_ok:
            return {}
        raise UninitialisedConfigError from None
    else:
        return values


def _parse_env_var(field_type: type, value: str):
    if attrs.has(field_type):
        return json.loads(value)
    elif field_type is bool:
        return attrs.converters.to_bool(value)
    return value


def read_env_vars(
    attrs_cls: type, values: Mapping[str, Any], parent_env_prefix: str | None = None
) -> dict[str, Any]:
    def iter_read():
        for field in attrs.fields(
            attrs.resolve_types(attrs_cls),
        ):
            if not field.init:
                continue

            value = values.get(field.name, attrs.NOTHING)

            metadata: FieldMetadata = field.metadata
            env_prefix = metadata.get('env_prefix')

            if env_prefix:
                env_key = f'{parent_env_prefix if env_prefix is True else env_prefix}_{field.name}'.upper()
                env_value = os.environ.get(env_key, attrs.NOTHING)
                if env_value is not attrs.NOTHING:
                    value = _parse_env_var(field.type, env_value)
                elif attrs.has(field.type):
                    value = read_env_vars(
                        field.type,
                        value if value is not attrs.NOTHING else {},
                        f'{env_prefix}_{field.name}',
                    )

            if value is not attrs.NOTHING:
                yield field.name, value

    return dict(iter_read())


config_converter = make_config_converter()


@config_converter.register_structure_hook_factory(attrs.has)
def _[T](type_: type[T]):
    "Allow passing in a structured attrs instance to ``structure``."
    structure = config_converter.gen_structure_attrs_fromdict(type_)

    def structure_wrapper(value: Mapping[str, object], type_: type):
        return value if isinstance(value, type_) else structure(value, type_)

    return structure_wrapper
