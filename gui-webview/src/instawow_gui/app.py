from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from functools import partial
from typing import Any

import anyio.from_thread
import anyio.to_thread
import toga
import toga.constants
import toga.style
from loguru import logger
from typing_extensions import Self

from . import json_rpc_server


class InstawowApp(toga.App):
    def __init__(self, debug: bool, **kwargs: object) -> None:
        super().__init__(
            formal_name='instawow-gui',
            app_id='org.instawow.instawow_gui',
            app_name='instawow_gui',
            icon='resources/instawow_gui',
            **kwargs,
        )
        self._debug = debug

    def startup(self) -> None:
        self.main_window = toga.MainWindow(title=self.formal_name, size=(800, 600))

        if os.name == 'nt':
            import ctypes

            # Enable high DPI support.
            ctypes.windll.user32.SetProcessDPIAware()

        self.main_window.content = web_view = toga.WebView(style=toga.style.Pack(flex=1))

        if self._debug:
            with suppress(AttributeError):
                web_view._impl.native.configuration.preferences.setValue(
                    True, forKey='developerExtrasEnabled'
                )

        if os.name == 'nt':
            from toga_winforms.widgets.webview import TogaWebBrowser

            def configure_webview2(sender: TogaWebBrowser, event_args: Any):
                if event_args.IsSuccess:
                    sender.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = False

            web_view._impl.native.CoreWebView2InitializationCompleted += configure_webview2

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
                text='Toggle Search Filter',
                shortcut=toga.Key.MOD_1 + toga.Key.G,
                group=toga.Group.EDIT,
                section=20,
                order=10,
            ),
            toga.Command(
                partial(dispatch_js_keyboard_event, action='activateViewInstalled'),
                text='Installed',
                shortcut=toga.Key.MOD_1 + toga.Key.L,
                group=toga.Group.WINDOW,
                section=20,
                order=10,
            ),
            toga.Command(
                partial(dispatch_js_keyboard_event, action='activateViewReconcile'),
                text='Unreconciled',
                group=toga.Group.WINDOW,
                section=20,
                order=20,
            ),
            toga.Command(
                partial(dispatch_js_keyboard_event, action='activateViewSearch'),
                text='Search',
                shortcut=toga.Key.MOD_1 + toga.Key.F,
                group=toga.Group.WINDOW,
                section=20,
                order=30,
            ),
        )

        async def startup(app: Self):
            async with anyio.from_thread.BlockingPortal() as portal:

                def run_json_rpc_server():
                    async def run():
                        web_app = await json_rpc_server.create_app((app.main_window, portal))
                        server_url, serve_forever = await json_rpc_server.run_app(web_app)

                        logger.debug(f'JSON-RPC server running on {server_url}')

                        set_server_url = partial(setattr, web_view, 'url')
                        portal.call(set_server_url, str(server_url))

                        await serve_forever()

                    # We don't want to inherit the parent thread's event loop policy,
                    # i.e. the rubicon loop on macOS.
                    policy = asyncio.DefaultEventLoopPolicy()
                    policy.new_event_loop().run_until_complete(run())

                await anyio.to_thread.run_sync(run_json_rpc_server)

                await portal.sleep_until_stopped()

        self.add_background_task(startup)
        self.main_window.show()
