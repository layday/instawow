# pyright: reportGeneralTypeIssues=warning
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

from functools import partial
import json
import platform

import toga
import toga.style

from . import json_rpc_server


class InstawowApp(toga.App):
    app: InstawowApp

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            formal_name='instawow-gui',
            app_id='org.instawow.instawow_gui',
            app_name='instawow_gui',
            icon='resources/instawow_gui',
            **kwargs,
        )

    async def _startup(self, native_app: object) -> None:
        server_url, serve = await json_rpc_server.prepare()
        self._iw_web_view.url = str(server_url)
        await serve()

    def startup(self) -> None:
        self.main_window = self.iw_window = toga.MainWindow(
            title=self.formal_name, size=(800, 600)
        )
        if platform.system() == 'Windows':
            from . import cef_adapter

            cef_adapter.load()

            self.iw_window.content = self._iw_web_view = toga.WebView(
                style=toga.style.Pack(flex=1), factory=cef_adapter.Factory
            )

        else:
            self.iw_window.content = self._iw_web_view = toga.WebView(
                style=toga.style.Pack(flex=1)
            )

        def dispatch_js_keyboard_event(_: toga.Command, *, action: str):
            event_args = json.dumps(
                {'detail': {'action': action}, 'bubbles': True, 'cancelable': True}
            )
            self._iw_web_view.invoke_javascript(
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

        self.add_background_task(self._startup)

        self.iw_window.show()
