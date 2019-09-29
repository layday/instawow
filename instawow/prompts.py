from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any, List, Optional

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from questionary import Choice as _Choice, confirm as _confirm
from questionary.prompts.common import InquirerControl, Separator, create_inquirer_layout
from questionary.question import Question

if TYPE_CHECKING:
    from .models import Pkg


class Choice(_Choice):

    def __init__(self, *args: Any, pkg: Optional[Pkg] = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pkg = pkg


qstyle = Style([('qmark', 'fg:ansicyan'),
                ('answer', 'fg: nobold'),
                ('hilite', 'fg:ansimagenta'),
                ('skipped', 'fg:ansiyellow'),
                ('question', 'nobold'),
                ('x-question', 'bold'),])
skip = Choice([('', 'skip')], ())

confirm = partial(_confirm, style=qstyle)


def checkbox(message: str, choices: List[Choice]) -> Question:
    # This is a cut-down version of ``questionary.checkbox`` with the addition
    # of an <o> key binding for opening package URLs

    def get_prompt_tokens():
        tokens = [('class:x-question', message),]
        if ic.is_answered:
            tokens.append(('class:answer', '  done'))
        else:
            tokens.append(('class:instruction',
                           '  (use arrow keys to move, '
                           '<space> to select, '
                           '<o> to view in your browser and '
                           '<i> to invert)'))
        return tokens

    ic = InquirerControl(choices, None,
                         use_indicator=False, use_shortcuts=False, use_pointer=True)
    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _(event):
        event.app.exit(exception=KeyboardInterrupt, style='class:aborting')

    @bindings.add(' ', eager=True)
    def toggle(event):
        pointed_choice = ic.get_pointed_at().value
        if pointed_choice in ic.selected_options:
            ic.selected_options.remove(pointed_choice)
        else:
            ic.selected_options.append(pointed_choice)

    @bindings.add('i', eager=True)
    def invert(event):
        inverted_selection = [c.value for c in ic.choices if
                              not isinstance(c, Separator)
                              and c.value not in ic.selected_options
                              and not c.disabled]
        ic.selected_options = inverted_selection

    @bindings.add(Keys.Down, eager=True)
    @bindings.add('j', eager=True)
    def move_cursor_down(event):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    @bindings.add(Keys.Up, eager=True)
    @bindings.add('k', eager=True)
    def move_cursor_up(event):
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    @bindings.add(Keys.ControlM, eager=True)
    def set_answer(event):
        ic.is_answered = True
        event.app.exit(result=[c.value for c in ic.get_selected_values()])

    @bindings.add('o', eager=True)
    def open_url(event):
        pkg = ic.get_pointed_at().pkg
        if pkg:
            import webbrowser
            webbrowser.open(pkg.url)

    @bindings.add(Keys.Any)
    def other(event):
        # Disallow inserting other text
        pass

    layout = create_inquirer_layout(ic, get_prompt_tokens)
    app = Application(layout=layout, key_bindings=bindings, style=qstyle)
    return Question(app)


def select(message: str, choices: List[Choice]) -> Question:
    def get_prompt_tokens():
        tokens = [('', '- '),
                  ('class:x-question', message),]
        if ic.is_answered:
            answer = ''.join(t for _, t in ic.get_pointed_at().title)
            tokens += [('', '  '),
                       ('class:skipped' if answer == 'skip' else '', answer)]
        return tokens

    ic = InquirerControl(choices, None,
                         use_indicator=False, use_shortcuts=False, use_pointer=True)
    bindings = KeyBindings()

    @bindings.add(Keys.ControlQ, eager=True)
    @bindings.add(Keys.ControlC, eager=True)
    def _(event):
        event.app.exit(exception=KeyboardInterrupt, style='class:aborting')

    @bindings.add(Keys.Down, eager=True)
    @bindings.add('j', eager=True)
    def move_cursor_down(event):
        ic.select_next()
        while not ic.is_selection_valid():
            ic.select_next()

    @bindings.add(Keys.Up, eager=True)
    @bindings.add('k', eager=True)
    def move_cursor_up(event):
        ic.select_previous()
        while not ic.is_selection_valid():
            ic.select_previous()

    @bindings.add(Keys.ControlM, eager=True)
    def set_answer(event):
        ic.is_answered = True
        event.app.exit(result=ic.get_pointed_at().value)

    @bindings.add('o', eager=True)
    def open_url(event):
        pkg = ic.get_pointed_at().pkg
        if pkg:
            import webbrowser
            webbrowser.open(pkg.url)

    @bindings.add(Keys.Any)
    def other(event):
        # Disallow inserting other text
        pass

    layout = create_inquirer_layout(ic, get_prompt_tokens)
    app = Application(layout=layout, key_bindings=bindings, style=qstyle)
    return Question(app)
