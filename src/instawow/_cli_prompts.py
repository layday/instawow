# pyright: reportUnusedFunction=false

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Any, Generic, Literal, TypeVar, overload

import attrs
import cattrs
from prompt_toolkit.application import Application
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import IsDone
from prompt_toolkit.formatted_text import (
    AnyFormattedText,
    FormattedText,
    StyleAndTextTuples,
    to_formatted_text,
)
from prompt_toolkit.formatted_text.html import HTML
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (
    ConditionalContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.shortcuts.progress_bar import ProgressBar as _ProgressBar
from prompt_toolkit.shortcuts.progress_bar import ProgressBarCounter as _ProgressBarCounter
from prompt_toolkit.shortcuts.progress_bar import formatters as pb_formatters
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import ValidationError, Validator
from prompt_toolkit.widgets import Label
from typing_extensions import Never

from ._utils.compat import fauxfrozen
from ._utils.web import open_url

_T = TypeVar('_T')


class AttrsFieldValidator(Validator):
    "One-off validators for attrs fields."

    def __init__(self, attribute: attrs.Attribute[object], converter: cattrs.Converter) -> None:
        self._field_name = attribute.name
        self._FieldWrapper = attrs.make_class(
            '_FieldWrapper',
            {
                self._field_name: attrs.field(
                    default=attribute.default,
                    validator=attribute.validator,
                    repr=attribute.repr,
                    hash=attribute.hash,
                    init=attribute.init,
                    metadata=attribute.metadata,
                    type=attribute.type,
                    converter=attribute.converter,
                    kw_only=attribute.kw_only,
                    eq=attribute.eq,
                    order=attribute.order,
                    on_setattr=attribute.on_setattr,
                )
            },
        )
        self._converter = converter

    def validate(self, document: Document) -> None:
        try:
            self._converter.structure({self._field_name: document.text}, self._FieldWrapper)
        except Exception as exc:
            raise ValidationError(
                0, '\n'.join(cattrs.transform_error(exc, format_exception=lambda e, _: str(e)))
            ) from exc


@fauxfrozen
class Choice(Generic[_T]):
    label: str | StyleAndTextTuples
    value: _T
    disabled: bool = False
    browser_url: str | None = None


class _FauxPromptSession(Generic[_T]):
    def __init__(self, application: Application[_T]) -> None:
        self.application = application

    def prompt(self) -> _T:
        return self.application.run()

    async def prompt_async(self) -> _T:
        return await self.application.run_async()


_style = Style(
    [
        ('indicator', 'fg:ansicyan'),
        ('question', 'bold'),
        ('skipped', 'fg:ansiyellow'),
        ('attention', 'fg:ansimagenta'),
    ]
)


class _Skip(enum.Enum):
    Skip = enum.auto()


SKIP = _Skip.Skip
_skip_choice = Choice([('underline', 's'), ('', 'kip')], SKIP)


def confirm(message: str) -> PromptSession[bool]:
    bindings = KeyBindings()

    result = None

    @bindings.add('y')
    @bindings.add('Y')
    def yes(event: KeyPressEvent) -> None:
        nonlocal result
        result = True
        event.app.exit(result=result)

    @bindings.add('n')
    @bindings.add('N')
    def no(event: KeyPressEvent) -> None:
        nonlocal result
        result = False
        event.app.exit(result=result)

    @bindings.add(Keys.Enter)  # Override <enter> from the prompt session's base bindings
    @bindings.add(Keys.Any)
    def _(event: KeyPressEvent) -> None:
        "Disallow inserting other text."

    def get_messsage():
        tokens = [
            ('class:indicator', '?' if result is None else '✓' if result else '✗'),
            ('', ' '),
            ('class:question', message),
        ]
        if result is None:
            tokens += [('', '  (Y/n)')]
        return FormattedText(tokens)

    session = PromptSession[bool](
        get_messsage,
        key_bindings=bindings,
        style=_style,
    )
    return session


def path(
    message: str, *, only_directories: bool = False, validator: Validator | None = None
) -> PromptSession[str]:
    completer = PathCompleter(
        expanduser=True,
        only_directories=only_directories,
    )
    session = PromptSession[str](
        FormattedText(
            [('class:indicator', '>'), ('', ' '), ('class:question', message), ('', '  ')]
        ),
        completer=completer,
        style=_style,
        validator=validator,
    )
    return session


def password(message: str) -> PromptSession[str]:
    session = PromptSession[str](
        FormattedText(
            [('class:indicator', '>'), ('', ' '), ('class:question', message), ('', '  ')]
        ),
        is_password=True,
        style=_style,
    )
    return session


def select_multiple(
    message: str,
    choices: Sequence[Choice[_T]],
) -> _FauxPromptSession[list[_T]]:
    bindings = KeyBindings()

    answered = False

    position = 0
    selected_indices = set[int]()

    @bindings.add(Keys.ControlC)
    @bindings.add(Keys.SIGINT)
    def abort(event: KeyPressEvent):
        event.app.exit(exception=KeyboardInterrupt, style='class:aborting')

    @bindings.add(Keys.Up)
    def previous_item(event: KeyPressEvent):
        nonlocal position
        position = max(0, position - 1)

    @bindings.add(Keys.Down)
    def next_item(event: KeyPressEvent):
        nonlocal position
        position = min(len(choices) - 1, position + 1)

    @bindings.add(' ')
    def select_item(event: KeyPressEvent):
        nonlocal selected_indices
        selected_indices = selected_indices ^ {position}

    @bindings.add('o')
    @bindings.add('O')
    def open_item_browser_url(event: KeyPressEvent):
        choice_at_position = choices[position]
        if choice_at_position.browser_url:
            open_url(choice_at_position.browser_url)

    @bindings.add(Keys.Enter)
    def submit(event: KeyPressEvent):
        nonlocal answered
        answered = True
        event.app.exit(result=[choices[i].value for i in selected_indices])

    @bindings.add(Keys.Any)
    def _(event: KeyPressEvent):
        "Disallow inserting other text."

    def get_label_messsage():
        tokens = [
            ('class:indicator', '✓' if answered else '-'),
            ('', ' '),
            ('class:question', message),
        ]
        if not answered:
            tokens += [
                (
                    '',
                    '  (use arrow keys to move, <space> to select'
                    + (', <o> to open in browser' if any(c.browser_url for c in choices) else '')
                    + ' and <enter> to confirm)',
                )
            ]
        return FormattedText(tokens)

    def get_select_tokens():
        tokens = list[StyleAndTextTuples]()

        for i, choice in enumerate(choices):
            focussed = i == position
            if focussed:
                tokens += [('[SetCursorPosition]', '')]

            if choice.disabled:
                tokens += [('', ' ')]
            else:
                selected = i in selected_indices
                if selected:
                    tokens += [('class:checkbox-selected', '■')]
                else:
                    tokens += [('', '□')]

            tokens += [('', ' '), *to_formatted_text(choice.label), ('', '\n')]

        return tokens[:-1]

    app = Application[list[_T]](
        key_bindings=bindings,
        layout=Layout(
            HSplit(
                [
                    Label(get_label_messsage),
                    ConditionalContainer(
                        Window(FormattedTextControl(get_select_tokens, focusable=True)),
                        filter=~IsDone(),
                    ),
                ],
            )
        ),
        style=_style,
    )
    return _FauxPromptSession(app)


@overload
def select_one(
    message: str,
    choices: Sequence[Choice[_T]],
    *,
    can_skip: Literal[True],
    initial_value: _T | None = None,
) -> _FauxPromptSession[_T | Literal[_Skip.Skip]]: ...
@overload
def select_one(
    message: str,
    choices: Sequence[Choice[_T]],
    *,
    can_skip: Literal[False] = False,
    initial_value: _T | None = None,
) -> _FauxPromptSession[_T]: ...


def select_one(
    message: str,
    choices: Sequence[Choice[_T]],
    *,
    can_skip: bool = False,
    initial_value: _T | None = None,
) -> _FauxPromptSession[Any]:
    bindings = KeyBindings()

    answered = False

    combined_choices = [*choices, _skip_choice] if can_skip else choices
    positions = [i for i, c in enumerate(combined_choices) if not c.disabled]
    position = next(
        p for p in positions if initial_value is None or choices[p].value == initial_value
    )

    @bindings.add(Keys.ControlC)
    @bindings.add(Keys.SIGINT)
    def abort(event: KeyPressEvent):
        event.app.exit(exception=KeyboardInterrupt, style='class:aborting')

    @bindings.add(Keys.Up)
    def previous_item(event: KeyPressEvent):
        nonlocal position
        try:
            position = positions[positions.index(position) - 1]
        except IndexError:
            position = positions[-1]

    @bindings.add(Keys.Down)
    def next_item(event: KeyPressEvent):
        nonlocal position
        try:
            position = positions[positions.index(position) + 1]
        except IndexError:
            position = positions[0]

    @bindings.add('o')
    @bindings.add('O')
    def open_item_browser_url(event: KeyPressEvent):
        choice_at_position = combined_choices[position]
        if choice_at_position.browser_url:
            open_url(choice_at_position.browser_url)

    @bindings.add(Keys.Enter)
    def submit(event: KeyPressEvent):
        nonlocal answered
        answered = True
        event.app.exit(result=combined_choices[position].value)

    if can_skip:

        @bindings.add('s')
        def skip_question(event: KeyPressEvent):
            nonlocal answered, position
            answered = True
            position = positions[-1]
            event.app.exit(result=SKIP)

    @bindings.add(Keys.Any)
    def _(event: KeyPressEvent):
        "Disallow inserting other text."

    def get_label_messsage():
        tokens = [
            (
                'class:indicator',
                '✓' if answered and combined_choices[position] is not _skip_choice else '-',
            ),
            ('', ' '),
            ('class:question', message),
        ]
        if answered and combined_choices[position] is _skip_choice:
            tokens += [('class:skipped', '  (skipped)')]
        elif not answered:
            tokens += [
                (
                    '',
                    '  (use arrow keys to move'
                    + (
                        ', <o> to open in browser'
                        if any(c.browser_url for c in combined_choices)
                        else ''
                    )
                    + ' and <enter> to select)',
                )
            ]
        else:
            tokens += [
                ('', '  ('),
                *to_formatted_text(combined_choices[position].label),
                ('', ')'),
            ]
        return FormattedText(tokens)

    def get_select_tokens():
        tokens = list[StyleAndTextTuples]()

        for i, choice in enumerate(combined_choices):
            if choice.disabled:
                tokens += [('', ' ')]
            else:
                focussed = i == position
                if focussed:
                    tokens += [('[SetCursorPosition]', ''), ('class:radio-selected', '●')]
                else:
                    tokens += [('', '○')]

            tokens += [('', ' '), *to_formatted_text(choice.label), ('', '\n')]

        return tokens[:-1]

    app = Application[Any](
        key_bindings=bindings,
        layout=Layout(
            HSplit(
                [
                    Label(get_label_messsage),
                    ConditionalContainer(
                        Window(FormattedTextControl(get_select_tokens, focusable=True)),
                        filter=~IsDone(),
                    ),
                ],
            )
        ),
        style=_style,
    )
    return _FauxPromptSession(app)


class ProgressBar(_ProgressBarCounter[Never]):
    def __init__(
        self,
        *,
        progress_bar: _ProgressBar,
        is_download: bool,
        label: AnyFormattedText = '',
        total: int | None = None,
    ) -> None:
        super().__init__(progress_bar=progress_bar, label=label, total=total)
        self.is_download = is_download


class _DownloadProgress(pb_formatters.Progress):
    template = HTML('<current>{current:>3.1f}</current>/<total>{total:>3.1f}</total>MB')

    def format(
        self, progress_bar: _ProgressBar, progress: _ProgressBarCounter[object], width: int
    ):
        if isinstance(progress, ProgressBar) and not progress.is_download:
            return super().format(progress_bar, progress, width)

        return self.template.format(
            current=progress.items_completed / 2**20, total=(progress.total or 0) / 2**20
        )


def make_progress_bar_group() -> _ProgressBar:
    "``ProgressBar`` with download progress expressed in megabytes."
    return _ProgressBar(
        formatters=[
            pb_formatters.Label(),
            pb_formatters.Text(' '),
            pb_formatters.Percentage(),
            pb_formatters.Text(' '),
            pb_formatters.Bar(sym_a='#', sym_b='#', sym_c='.'),
            pb_formatters.Text(' '),
            _DownloadProgress(),
        ],
    )
