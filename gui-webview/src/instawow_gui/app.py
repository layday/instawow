# pyright: reportGeneralTypeIssues=warning
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import asyncio
from functools import partial
import json
import platform
import threading

import toga
import toga.style


class InstawowApp(toga.App):
    app: InstawowApp

    def __init__(self, **kwargs: object) -> None:
        from . import json_rpc_server

        server_loop = asyncio.new_event_loop()
        server_url, serve = server_loop.run_until_complete(json_rpc_server.prepare())
        self.iw_server_url = str(server_url)
        server_thread = threading.Thread(
            target=lambda: server_loop.run_until_complete(serve()), name='iw-server-thread'
        )
        server_thread.start()

        super().__init__(
            formal_name='instawow-gui',
            app_id='org.instawow.instawow_gui',
            app_name='instawow_gui',
            icon='resources/instawow_gui',
            **kwargs,
        )
        self.loop = asyncio.get_event_loop()

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

        def dispatch_js_keyboard_event(_: toga.Command, *, action: str):
            event_args = json.dumps(
                {'detail': {'action': action}, 'bubbles': True, 'cancelable': True}
            )
            self.iw_webview.invoke_javascript(
                f'document.dispatchEvent(new CustomEvent("togaSimulateKeypress", {event_args}));'
            )

        self.commands.add(
            toga.Command(
                partial(dispatch_js_keyboard_event, action='toggleSearchFilter'),
                label='Toggle Search Filter',
                shortcut=toga.Key.MOD_1 + toga.Key.G,
                group=toga.Group.EDIT,
                section=20,
                order=10,
            ),
            toga.Command(
                partial(dispatch_js_keyboard_event, action='activateViewInstalled'),
                label='Installed',
                shortcut=toga.Key.MOD_1 + toga.Key.L,
                group=toga.Group.WINDOW,
                section=20,
                order=10,
            ),
            toga.Command(
                partial(dispatch_js_keyboard_event, action='activateViewReconcile'),
                label='Unreconciled',
                group=toga.Group.WINDOW,
                section=20,
                order=20,
            ),
            toga.Command(
                partial(dispatch_js_keyboard_event, action='activateViewSearch'),
                label='Search',
                shortcut=toga.Key.MOD_1 + toga.Key.F,
                group=toga.Group.WINDOW,
                section=20,
                order=30,
            ),
        )

        self.iw_window.show()
