from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import threading
from collections.abc import Callable
from enum import StrEnum
from functools import partial

import toga
import toga.constants
import toga.style.pack

from . import _json_rpc_server

_loop_factory = asyncio.DefaultEventLoopPolicy().new_event_loop


class _TogaSimulateKeypressAction(StrEnum):
    ToggleSearchFilter = 'toggleSearchFilter'
    ActivateViewInstalled = 'activateViewInstalled'
    ActivateViewReconcile = 'activateViewReconcile'
    ActivateViewSearch = 'activateViewSearch'


class _App(toga.App):
    def __start_json_rpc_server(self, on_started: Callable[[str], None]):
        def start_json_rpc_server():
            async def main():
                async with _json_rpc_server.run_web_app(
                    await _json_rpc_server.create_web_app(self)
                ) as server_url:
                    server_url_future.set_result(str(server_url))
                    await wait_future

            loop.run_until_complete(main())

        def stop_json_rpc_server():
            loop.call_soon_threadsafe(wait_future.set_result, None)
            json_rpc_server_thread.join()

        loop = _loop_factory()
        wait_future = loop.create_future()

        server_url_future = concurrent.futures.Future[str]()

        json_rpc_server_thread = threading.Thread(
            target=start_json_rpc_server, name='_json_rpc_server'
        )
        json_rpc_server_thread.start()

        server_url = server_url_future.result()
        on_started(server_url)

        def on_app_exit(app: toga.App, /, **kwargs: object):
            stop_json_rpc_server()
            return True

        self.on_exit = on_app_exit  # pyright: ignore[reportAttributeAccessIssue]

    def startup(self) -> None:
        if sys.platform == 'win32':
            import ctypes

            # Enable high DPI support.
            ctypes.windll.user32.SetProcessDPIAware()

        def dispatch_js_keyboard_event(command: toga.Command, **kwargs: object):
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
                group=toga.Group.EDIT,
                section=20,
                order=10,
            ),
            toga.Command(
                partial(
                    dispatch_js_keyboard_event,
                    action=_TogaSimulateKeypressAction.ActivateViewInstalled,
                ),
                text='Installed',
                shortcut=toga.Key.MOD_1 + toga.Key.L,
                group=toga.Group.WINDOW,
                section=20,
                order=10,
            ),
            toga.Command(
                partial(
                    dispatch_js_keyboard_event,
                    action=_TogaSimulateKeypressAction.ActivateViewReconcile,
                ),
                text='Unreconciled',
                group=toga.Group.WINDOW,
                section=20,
                order=20,
            ),
            toga.Command(
                partial(
                    dispatch_js_keyboard_event,
                    action=_TogaSimulateKeypressAction.ActivateViewSearch,
                ),
                text='Search',
                shortcut=toga.Key.MOD_1 + toga.Key.F,
                group=toga.Group.WINDOW,
                section=20,
                order=30,
            ),
        )

        web_view = toga.WebView(style=toga.style.pack.Pack(flex=1))

        self.__start_json_rpc_server(partial(setattr, web_view, 'url'))

        self.main_window = main_window = toga.MainWindow(
            title=self.formal_name, size=(800, 600), content=web_view
        )
        main_window.show()


def make_app(version: str) -> toga.App:
    return _App(
        formal_name='instawow-gui',
        app_id='org.instawow.instawow_gui',
        app_name='instawow_gui',
        icon='_resources/instawow_gui',
        version=version,
    )
