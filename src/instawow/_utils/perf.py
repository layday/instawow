from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


@contextmanager
def time_op(on_complete: Callable[[float], None]) -> Iterator[None]:
    start = time.perf_counter()
    yield
    on_complete(time.perf_counter() - start)
