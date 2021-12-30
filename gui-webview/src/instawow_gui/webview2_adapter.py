# Adapted from https://github.com/r0x0r/pywebview/blob/master/webview/platforms/edgechromium.py.

from __future__ import annotations

import importlib.resources
import os

import clr
from toga_winforms.libs import Uri
from toga_winforms.widgets.base import Widget

from . import webview2

core_lib = importlib.resources.path(webview2, 'Microsoft.Web.WebView2.Core.dll').__enter__()
winforms_lib = importlib.resources.path(
    webview2, 'Microsoft.Web.WebView2.WinForms.dll'
).__enter__()

clr.AddReference(os.fspath(core_lib))
clr.AddReference(os.fspath(winforms_lib))

from Microsoft.Web.WebView2.Core import CoreWebView2Environment, WebView2RuntimeNotFoundException
from Microsoft.Web.WebView2.WinForms import WebView2


def is_webview2_installed():
    try:
        CoreWebView2Environment.GetAvailableBrowserVersionString()
    except WebView2RuntimeNotFoundException:
        return False
    else:
        return True


class WebView2Widget(Widget):
    def create(self):
        self.native = WebView2()
        self.native.interface = self.interface

        def on_initialization_completed(sender, event_args):
            pass

        self.native.CoreWebView2InitializationCompleted += on_initialization_completed

    def set_on_key_down(self, handler: object) -> None:
        pass

    def set_on_webview_load(self, handler: object) -> None:
        pass

    def set_url(self, value: str | None) -> None:
        if value is not None:
            self.native.Source = Uri(value)

    def set_content(self, root_url: str, content: str) -> None:
        raise NotImplementedError

    def set_user_agent(self, value: str) -> None:
        pass

    async def evaluate_javascript(self, javascript: str) -> None:
        raise NotImplementedError

    def invoke_javascript(self, javascript: str) -> None:
        self.native.ExecuteScriptAsync(javascript)


class Factory:
    WebView = WebView2Widget
