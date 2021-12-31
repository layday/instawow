from __future__ import annotations

from functools import partial
import json
import os

import click
from loguru import logger
import toga
import toga.constants
import toga.style

from . import json_rpc_server


class InstawowApp(toga.App):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            formal_name='instawow-gui',
            app_id='org.instawow.instawow_gui',
            app_name='instawow_gui',
            icon='resources/instawow_gui',
            **kwargs,
        )

    def startup(self) -> None:
        self.main_window = toga.MainWindow(title=self.formal_name, size=(800, 600))
        if os.name == 'nt':
            import ctypes

            from . import webview2_adapter

            # Enable high DPI support.
            ctypes.windll.user32.SetProcessDPIAware()

            if not webview2_adapter.is_webview2_installed():
                self.main_window.content = toga.Box(
                    style=toga.style.Pack(
                        alignment=toga.constants.CENTER, direction=toga.constants.COLUMN
                    ),
                    children=[
                        toga.Label(
                            'WebView2 is required to run instawow.  Please install it '
                            'and restart instawow.',
                            style=toga.style.Pack(text_align=toga.constants.CENTER, padding=10),
                        ),
                        toga.Button(
                            'Download WebView2',
                            on_press=lambda _: click.launch(
                                'https://developer.microsoft.com/en-us/microsoft-edge/webview2/'
                            ),
                            style=toga.style.Pack(width=200),
                        ),
                    ],
                )
                self.main_window.show()
                return

            self.main_window.content = web_view = toga.WebView(
                style=toga.style.Pack(flex=1), factory=webview2_adapter.Factory
            )

        else:
            self.main_window.content = web_view = toga.WebView(style=toga.style.Pack(flex=1))

        def dispatch_js_keyboard_event(_: toga.Command, *, action: str):
            event_args = json.dumps(
                {'detail': {'action': action}, 'bubbles': True, 'cancelable': True}
            )
            web_view.invoke_javascript(
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

        async def startup() -> None:
            web_app = await json_rpc_server.create_app(self.main_window)
            server_url, serve = await json_rpc_server.run_app(web_app)
            logger.debug(f'JSON-RPC server running on {server_url}')
            web_view.url = str(server_url)
            await serve()

        serve_task = self._impl.loop.create_task(startup())
        self.on_exit = lambda _: serve_task.cancel()

        self.main_window.show()
