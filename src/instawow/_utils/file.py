from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from functools import lru_cache
from itertools import chain
from pathlib import Path
from shutil import move
from tempfile import gettempdir, mkdtemp

_instawowt = Path(gettempdir(), 'instawowt')


def reveal_folder(path: str | os.PathLike[str]) -> None:
    if sys.platform == 'win32':
        os.startfile(path, 'explore')
    else:
        import click

        click.launch(os.fspath(path), locate=True)


@lru_cache(1)
def _make_instawowt():
    _instawowt.mkdir(exist_ok=True)


def trash(paths: Iterable[os.PathLike[str]], *, missing_ok: bool = True) -> None:
    paths_iter = iter(paths)
    first_path = next(paths_iter, None)

    if first_path is None:
        return

    _make_instawowt()
    parent_folder = mkdtemp(dir=_instawowt, prefix=f'deleted-{Path(first_path).name}-')

    exc_classes = FileNotFoundError if missing_ok else ()

    for path in chain((first_path,), paths_iter):
        try:
            move(path, parent_folder)
        except exc_classes:
            pass
