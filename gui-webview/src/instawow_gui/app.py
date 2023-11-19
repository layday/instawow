from __future__ import annotations

import asyncio
import json
import sys
from contextlib import suppress
from functools import partial
from typing import cast

import anyio.from_thread
import anyio.to_thread
import toga
import toga.constants
import toga.style.pack
from loguru import logger

from instawow.utils import StrEnum

from . import json_rpc_server


class _TogaSimulateKeypressAction(StrEnum):
    ToggleSearchFilter = 'toggleSearchFilter'
    ActivateViewInstalled = 'activateViewInstalled'
    ActivateViewReconcile = 'activateViewReconcile'
    ActivateViewSearch = 'activateViewSearch'


class InstawowApp(toga.App):
    def __init__(self, debug: bool, **kwargs) -> None:
        self.__debug = debug

        super().__init__(
            formal_name='instawow-gui',
            app_id='org.instawow.instawow_gui',
            app_name='instawow_gui',
            icon='resources/instawow_gui',
            **kwargs,
        )

    def startup(self, **kwargs) -> None:
        self.main_window = toga.MainWindow(title=self.formal_name, size=(800, 600))

        if sys.platform == 'win32':
            import ctypes

            # Enable high DPI support.
            ctypes.windll.user32.SetProcessDPIAware()

        self.main_window.content = web_view = toga.WebView(style=toga.style.pack.Pack(flex=1))

        if self.__debug:
            with suppress(AttributeError):
                web_view._impl.native.configuration.preferences.setValue(
                    True, forKey='developerExtrasEnabled'
                )

        if sys.platform == 'win32':
            web_view_impl = web_view._impl

            def configure_webview2(sender, event_args):
                if event_args.IsSuccess:
                    web_view_impl.native.CoreWebView2.Settings.AreBrowserAcceleratorKeysEnabled = (
                        False
                    )

            web_view_impl.native.CoreWebView2InitializationCompleted += configure_webview2

        def dispatch_js_keyboard_event(command: toga.Command, **kwargs):
            event_args = json.dumps(
                {'detail': {'action': kwargs['action']}, 'bubbles': True, 'cancelable': True}
            )
            web_view.evaluate_javascript(
                f'document.dispatchEvent(new CustomEvent("togaSimulateKeypress", {event_args}));'
            )

            return True

        self.commands.add(
            toga.Command(
                partial(
                    dispatch_js_keyboard_event,
                    action=_TogaSimulateKeypressAction.ToggleSearchFilter,
                ),
                text='Toggle Search Filter',
                shortcut=toga.Key.MOD_1 + toga.Key.G,
                group=cast(toga.Group, toga.Group.EDIT),
                section=20,
                order=10,
            ),
        )
        self.commands.add(
            toga.Command(
                partial(
                    dispatch_js_keyboard_event,
                    action=_TogaSimulateKeypressAction.ActivateViewInstalled,
                ),
                text='Installed',
                shortcut=toga.Key.MOD_1 + toga.Key.L,
                group=cast(toga.Group, toga.Group.WINDOW),
                section=20,
                order=10,
            ),
        )
        self.commands.add(
            toga.Command(
                partial(
                    dispatch_js_keyboard_event,
                    action=_TogaSimulateKeypressAction.ActivateViewReconcile,
                ),
                text='Unreconciled',
                group=cast(toga.Group, toga.Group.WINDOW),
                section=20,
                order=20,
            ),
        )
        self.commands.add(
            toga.Command(
                partial(
                    dispatch_js_keyboard_event,
                    action=_TogaSimulateKeypressAction.ActivateViewSearch,
                ),
                text='Search',
                shortcut=toga.Key.MOD_1 + toga.Key.F,
                group=cast(toga.Group, toga.Group.WINDOW),
                section=20,
                order=30,
            ),
        )

        async def startup():
            async with anyio.from_thread.BlockingPortal() as portal:

                def run_json_rpc_server():
                    async def run():
                        web_app = await json_rpc_server.create_app((self.main_window, portal))
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

        main_task = self.loop.create_task(startup())

        def on_exit(app: toga.App, **kwargs):
            return main_task.cancel()

        self.on_exit = on_exit

        self.main_window.show()
