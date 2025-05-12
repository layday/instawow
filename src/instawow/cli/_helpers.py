from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

import click
import click.types

from .._utils.iteration import bucketise


class EnumValueChoiceParam[EnumT: Enum](click.Choice[EnumT]):
    def __init__(
        self,
        choice_enum: type[EnumT],
    ):
        super().__init__(choices=list(choice_enum))
        self.__choice_enum = choice_enum

    def normalize_choice(self, choice: EnumT, ctx: click.Context | None) -> str:
        return super().normalize_choice(self.__choice_enum(choice), ctx)


class ManyOptionalChoiceValueParam[ParamT](click.types.CompositeParamType):
    name = 'optional-choice-value'

    def __init__(
        self,
        choice_param: click.Choice[ParamT],
        *,
        value_types: Mapping[str, type] = {},
    ):
        super().__init__()
        self.__choice_param = choice_param
        self.__value_types = {k: click.types.convert_type(v) for k, v in value_types.items()}

    @property
    def arity(self):
        return -1

    def convert(
        self, value: tuple[str, ...], param: click.Parameter | None, ctx: click.Context | None
    ):
        def do_convert(raw_entries: tuple[str, ...]):
            converter = self.__choice_param
            value_types = self.__value_types
            for raw_entry in raw_entries:
                key, sep, value = raw_entry.partition('=')
                value_type = value_types.get(key)
                value = value if sep else None
                yield (
                    converter.convert(key, param, ctx),
                    value_type.convert(value, param, ctx) if value_type and value else value,
                )

        return dict(do_convert(value))

    def get_metavar(self, param: click.Parameter, ctx: click.Context):
        return f'{{{",".join(map(str, self.__choice_param.choices))}}}[=VALUE]'


class SectionedHelpGroup(click.Group):
    group_class = type

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter):
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
