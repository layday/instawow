from __future__ import annotations

import asyncio
from functools import partial
import json
import platform
from typing import ClassVar

import toga
import toga.style


class InstawowApp(toga.App):
    running_app: ClassVar[InstawowApp]

    def __init__(self, server_url: str, **kwargs: object) -> None:
        super().__init__(
            formal_name='instawow',
            app_id='org.instawow.gui',
            app_name='instawow_gui',
            **kwargs,
        )

        self.__class__.running_app = self

        self.loop = asyncio.get_event_loop()
        self.iw_server_url = server_url

    def startup(self) -> None:
        self.main_window = self.iw_window = toga.MainWindow(
            title=self.formal_name, size=(800, 600)
        )
        self.iw_window.content = self.iw_webview = toga.WebView(
            url=self.iw_server_url, style=toga.style.Pack(flex=1)
        )

        # ``toga-winforms`` does not implement ``invoke_javascript`` for WebView
        if platform.system() != 'Windows':
            view_group = toga.Group('View')
            self.commands.add(
                toga.Command(
                    partial(self.iw_dispatch_keyboard_event, action='focusSearchBox'),
                    label='Search',
                    shortcut=toga.Key.MOD_1 + toga.Key.F,
                    group=view_group,
                    section=1,
                    order=0,
                ),
                toga.Command(
                    partial(self.iw_dispatch_keyboard_event, action='toggleFiltering'),
                    label='Toggle filtering',
                    shortcut=toga.Key.MOD_1 + toga.Key.G,
                    group=view_group,
                    section=1,
                    order=1,
                ),
            )

        self.iw_window.show()

    def iw_dispatch_keyboard_event(self, command: toga.Command, action: str) -> None:
        event_args = json.dumps(
            {'detail': {'action': action}, 'bubbles': True, 'cancelable': True}
        )
        self.iw_webview.invoke_javascript(
            f'document.dispatchEvent(new CustomEvent("togaSimulateKeypress", {event_args}));'
        )

    def iw_select_folder(self, initial_folder: str | None = None) -> str | None:
        try:
            (selection,) = self.iw_window.select_folder_dialog('Select folder', initial_folder)
            return selection
        except ValueError:
            pass

    def iw_confirm(self, title: str, message: str) -> bool:
        return self.iw_window.confirm_dialog(title, message)
