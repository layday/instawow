from __future__ import annotations

import atexit
import sys
import threading

from cefpython3 import cefpython as cef
from toga_winforms.widgets.box import Box

_cef_loaded = False


def load() -> None:
    global _cef_loaded

    if not _cef_loaded:
        sys.excepthook = cef.ExceptHook
        cef.Initialize(
            settings={
                'cache_path': '',
                'multi_threaded_message_loop': True,
            },
            switches={
                # To enable ``filter-backdrop`` support
                'enable-experimental-web-platform-features': '',
            },
        )
        atexit.register(cef.Shutdown)
        _cef_loaded = True


class _CefWidget(Box):
    def create(self):
        super().create()

        self.window_created = threading.Event()
        window_info = cef.WindowInfo()
        window_info.SetAsChild(self.native.Handle.ToInt32())

        def create_browser(widget: _CefWidget, window_info: cef.WindowInfo) -> None:
            widget.browser = cef.CreateBrowserSync(window_info)
            widget.browser.WasResized()
            self.window_created.set()

        cef.PostTask(cef.TID_UI, create_browser, self, window_info)

    def set_bounds(self, x: int, y: int, width: int, height: int) -> None:
        super().set_bounds(x, y, width, height)

        def update_window_size():
            cef.WindowUtils.OnSize(self.native.Handle.ToInt32(), 0, 0, 0)

        cef.PostTask(cef.TID_UI, update_window_size)

    def set_on_key_down(self, handler: object) -> None:
        pass

    def set_on_webview_load(self, handler: object) -> None:
        pass

    def set_url(self, value: str) -> None:
        def load_url():
            self.window_created.wait()
            self.browser.LoadUrl(value)

        cef.PostTask(cef.TID_UI, load_url)

    def set_content(self, root_url: str, content: str) -> None:
        raise NotImplementedError

    def set_user_agent(self, value: str) -> None:
        pass

    async def evaluate_javascript(self, javascript: str) -> None:
        raise NotImplementedError

    def invoke_javascript(self, javascript: str) -> None:
        def execute_javascript():
            self.window_created.wait()
            self.browser.ExecuteJavascript(javascript)

        cef.PostTask(cef.TID_UI, execute_javascript)


class Factory:
    WebView = _CefWidget
