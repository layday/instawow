from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple, Type

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from prompt_toolkit.validation import ValidationError, Validator
import pydantic
from questionary import Choice, confirm as _confirm
from questionary.prompts.common import InquirerControl, Separator, create_inquirer_layout
from questionary.question import Question

if TYPE_CHECKING:
    from prompt_toolkit.document import Document

    from .models import Pkg


class PydanticValidator(Validator):
    "One-off validators for Pydantic model fields."

    def __init__(self, model: Type[pydantic.BaseModel], field: str) -> None:
        self.model = model
        self.field = field

    def validate(self, document: Document) -> None:
        try:
            self.model.parse_obj({self.field: document.text})
        except pydantic.ValidationError as error:
            error_at_loc = next((e for e in error.errors() if e['loc'] == (self.field,)), None)
            if error_at_loc:
                raise ValidationError(0, error_at_loc['msg'])


class PkgChoice(Choice):
    def __init__(self, *args: Any, pkg: Optional[Pkg] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pkg = pkg


qstyle = Style(
    [
        ('qmark', 'fg:ansicyan'),
        ('answer', 'fg: nobold'),
        ('highlight-sub', 'fg:ansimagenta'),
        ('skipped', 'fg:ansiyellow'),
        ('question', 'nobold'),
        ('x-question', 'bold'),
    ]
)

skip = Choice([('', 'skip')], ())  # type: ignore

confirm = partial(_confirm, style=qstyle)


def checkbox(message: str, choices: Sequence[Choice], **prompt_kwargs: Any) -> Question:
    # This is a cut-down version of ``questionary.checkbox`` with the addition
    # of an <o> key binding for opening package URLs

    def get_prompt_tokens():
        tokens: List[Tuple[str, str]] = [('class:x-question', message)]
        if ic.is_answered:
            tokens = [*tokens, (('class:answer', '  done'))]
        else:
            tokens = [
                *tokens,
                (
                    (
                        'class:instruction',
                        '  (use arrow keys to move, <space> to select, <o> to view in your browser)',
                    )
                ),
            ]
        return tokens

    ic = InquirerControl(
        choices, None, use_indicator=False, use_shortcuts=False, use_pointer=True  # type: ignore
    )
    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _(event: Any):
        event.app.exit(exception=KeyboardInterrupt, style='class:aborting')

    @bindings.add(' ', eager=True)
    def toggle(event: Any):
        pointed_choice = ic.get_pointed_at().value
        if pointed_choice in ic.selected_options:
            ic.selected_options.remove(pointed_choice)
        else:
            ic.selected_options.append(pointed_choice)

    @bindings.add('i', eager=True)
    def invert(event: Any):
        inverted_selection = [
            c.value
            for c in ic.choices
            if not isinstance(c, Separator)
            and c.value not in ic.selected_options
            and not c.disabled
        ]
        ic.selected_options = inverted_selection

    @bindings.add(Keys.Down, eager=True)
    @bindings.add('j', eager=True)
    def move_cursor_down(event: Any):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    @bindings.add(Keys.Up, eager=True)
    @bindings.add('k', eager=True)
    def move_cursor_up(event: Any):
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    @bindings.add(Keys.ControlM, eager=True)
    def set_answer(event: Any):
        ic.is_answered = True
        event.app.exit(result=[c.value for c in ic.get_selected_values()])

    @bindings.add('o', eager=True)
    def open_url(event: Any):
        pkg = ic.get_pointed_at().pkg
        if pkg:
            import webbrowser

            webbrowser.open(pkg.url)

    @bindings.add(Keys.Any)
    def other(event: Any):
        # Disallow inserting other text
        pass

    layout = create_inquirer_layout(ic, get_prompt_tokens, **prompt_kwargs)
    app = Application(layout=layout, key_bindings=bindings, style=qstyle, **prompt_kwargs)
    return Question(app)


def select(message: str, choices: Sequence[Choice], **prompt_kwargs: Any) -> Question:
    def get_prompt_tokens():
        tokens: List[Tuple[str, str]] = [('', '- '), ('class:x-question', message)]
        if ic.is_answered:
            answer = ''.join(t for _, t in ic.get_pointed_at().title)
            tokens = [*tokens, ('', '  '), ('class:skipped' if answer == 'skip' else '', answer)]
        return tokens

    ic = InquirerControl(
        choices, None, use_indicator=False, use_shortcuts=False, use_pointer=True  # type: ignore
    )
    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _(event: Any):
        event.app.exit(exception=KeyboardInterrupt, style='class:aborting')

    @bindings.add(Keys.Down, eager=True)
    @bindings.add('j', eager=True)
    def move_cursor_down(event: Any):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    @bindings.add(Keys.Up, eager=True)
    @bindings.add('k', eager=True)
    def move_cursor_up(event: Any):
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    @bindings.add(Keys.ControlM, eager=True)
    def set_answer(event: Any):
        ic.is_answered = True
        event.app.exit(result=ic.get_pointed_at().value)

    @bindings.add('o', eager=True)
    def open_url(event: Any):
        pkg = getattr(ic.get_pointed_at(), 'pkg', None)
        if pkg:
            import webbrowser

            webbrowser.open(pkg.url)

    @bindings.add('s', eager=True)
    def skip(event: Any):
        ic.pointed_at = -1
        ic.is_answered = True
        event.app.exit(result=ic.get_pointed_at().value)

    @bindings.add(Keys.Any)
    def other(event: Any):
        # Disallow inserting other text
        pass

    layout = create_inquirer_layout(ic, get_prompt_tokens, **prompt_kwargs)
    app = Application(layout=layout, key_bindings=bindings, style=qstyle, **prompt_kwargs)
    return Question(app)
