from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, TypeVar

import click

from .._utils.compat import StrEnum
from .._utils.iteration import bucketise

_TStrEnum = TypeVar('_TStrEnum', bound=StrEnum)


class StrEnumChoiceParam(Generic[_TStrEnum], click.Choice):
    def __init__(
        self,
        choice_enum: type[_TStrEnum],
        case_sensitive: bool = True,
    ) -> None:
        super().__init__(
            choices=list(choice_enum),
            case_sensitive=case_sensitive,
        )
        self.__choice_enum = choice_enum

    def convert(
        self, value: Any, param: click.Parameter | None, ctx: click.Context | None
    ) -> _TStrEnum:
        converted_value = super().convert(value, param, ctx)
        return self.__choice_enum(converted_value)


class ManyOptionalChoiceValueParam(click.types.CompositeParamType):
    name = 'optional-choice-value'

    def __init__(
        self,
        choice_param: click.Choice,
        *,
        value_types: Mapping[str, click.types.ParamType] = {},
    ) -> None:
        super().__init__()
        self.__choice_param = choice_param
        self.__value_types = value_types

    def __parse_value(self, value: tuple[str, ...]):
        return (
            (k, v if s else None, self.__choice_param, vc)
            for r in value
            for k, s, v in (r.partition('='),)
            for vc in (self.__value_types.get(k),)
        )

    @property
    def arity(self) -> int:
        return -1

    def convert(
        self, value: tuple[str, ...], param: click.Parameter | None, ctx: click.Context | None
    ) -> Any:
        return {
            kc.convert(k, param, ctx): vc.convert(v, param, ctx) if vc and v else v
            for k, v, kc, vc in self.__parse_value(value)
        }

    def get_metavar(self, param: click.Parameter) -> str:
        return f'{{{",".join(self.__choice_param.choices)}}}[=VALUE]'


class SectionedHelpGroup(click.Group):
    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        command_sections = bucketise(
            ((s, c) for s, c in self.commands.items() if not c.hidden),
            key=lambda c: 'Command groups' if isinstance(c[1], click.Group) else 'Commands',
        )
        if command_sections:
            for section_name, commands in command_sections.items():
                with formatter.section(section_name):
                    limit = formatter.width - 6 - max(len(s) for s, _ in commands)
                    formatter.write_dl(
                        [(s, c.get_short_help_str(limit)) for s, c in commands],
                    )
