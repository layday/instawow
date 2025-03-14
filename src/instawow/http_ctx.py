from __future__ import annotations

import contextvars as cv

from . import http

_web_client_var = cv.ContextVar['http.CachedSession']('_web_client_var')


@object.__new__
class web_client:
    def __call__(self) -> http.CachedSession:
        return _web_client_var.get()

    set = staticmethod(_web_client_var.set)
    reset = staticmethod(_web_client_var.reset)
