# pyright: reportMissingImports=false

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
            formal_name='instawow-gui',
            app_id='org.instawow.instawow_gui',
            app_name='instawow_gui',
            icon='resources/instawow_gui',
            **kwargs,
        )

        self.__class__.running_app = self

        self.loop = asyncio.get_event_loop()
        self.iw_server_url = server_url

    def startup(self) -> None:
        self.main_window = self.iw_window = toga.MainWindow(
            title=self.formal_name, size=(800, 600)
        )

        if platform.system() == 'Windows':
            from . import cef_adapter

            cef_adapter.load()

            self.iw_window.content = self.iw_webview = toga.WebView(
                url=self.iw_server_url,
                style=toga.style.Pack(flex=1),
                factory=cef_adapter.Factory,
            )

        else:
            self.iw_window.content = self.iw_webview = toga.WebView(
                url=self.iw_server_url, style=toga.style.Pack(flex=1)
            )

        if platform.system() == 'Darwin':
            from rubicon.objc import send_message

            def send_message_to_wkwebview(_: toga.Command, *, selector: str):
                send_message(
                    self.iw_webview._impl.native,  # type: ignore
                    selector,
                    restype=None,
                    argtypes=[],
                )

            edit_group = toga.Group('Edit')
            self.commands.add(
                toga.Command(
                    partial(send_message_to_wkwebview, selector='cut:'),
                    label='Cut',
                    shortcut=toga.Key.MOD_1 + toga.Key.X,
                    group=edit_group,
                    section=1,
                    order=1,
                ),
                toga.Command(
                    partial(send_message_to_wkwebview, selector='copy:'),
                    label='Copy',
                    shortcut=toga.Key.MOD_1 + toga.Key.C,
                    group=edit_group,
                    section=1,
                    order=2,
                ),
                toga.Command(
                    partial(send_message_to_wkwebview, selector='paste:'),
                    label='Paste',
                    shortcut=toga.Key.MOD_1 + toga.Key.V,
                    group=edit_group,
                    section=1,
                    order=3,
                ),
                toga.Command(
                    partial(send_message_to_wkwebview, selector='selectAll:'),
                    label='Select All',
                    shortcut=toga.Key.MOD_1 + toga.Key.A,
                    group=edit_group,
                    section=2,
                    order=1,
                ),
            )

        def dispatch_js_keyboard_event(_: toga.Command, *, action: str):
            event_args = json.dumps(
                {'detail': {'action': action}, 'bubbles': True, 'cancelable': True}
            )
            self.iw_webview.invoke_javascript(
                f'document.dispatchEvent(new CustomEvent("togaSimulateKeypress", {event_args}));'
            )

        view_group = toga.Group('View')
        self.commands.add(
            toga.Command(
                partial(dispatch_js_keyboard_event, action='focusSearchBox'),
                label='Search',
                shortcut=toga.Key.MOD_1 + toga.Key.F,
                group=view_group,
                section=2,
                order=1,
            ),
            toga.Command(
                partial(dispatch_js_keyboard_event, action='toggleFiltering'),
                label='Toggle filtering',
                shortcut=toga.Key.MOD_1 + toga.Key.G,
                group=view_group,
                section=2,
                order=2,
            ),
        )

        self.iw_window.show()

    def iw_select_folder(self, initial_folder: str | None = None) -> str | None:
        try:
            (selection,) = self.iw_window.select_folder_dialog('Select folder', initial_folder)
            return selection
        except ValueError:
            return None

    def iw_confirm(self, title: str, message: str) -> bool:
        return self.iw_window.confirm_dialog(title, message)
