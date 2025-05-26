from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterable
from functools import lru_cache
from itertools import chain
from pathlib import Path


def expand_path(value: os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve()


def reveal_folder(path: str | os.PathLike[str]) -> None:
    if sys.platform == 'win32':
        os.startfile(path, 'explore')
    else:
        import click

        click.launch(os.fspath(path), locate=True)


@lru_cache(1)
def make_instawowt():
    from tempfile import gettempdir

    instawowt = Path(gettempdir(), 'instawowt')
    instawowt.mkdir(exist_ok=True)
    return instawowt


trash = None

if sys.platform == 'darwin':
    _maybe_trash_bin = shutil.which('/usr/bin/trash')  # Added in macOS 14.
    if _maybe_trash_bin:
        _trash_bin = _maybe_trash_bin

        def _trash_darwin(paths: Iterable[os.PathLike[str]]) -> None:
            import subprocess

            try:
                subprocess.run(
                    [_trash_bin, *(os.fspath(p) for p in paths)], capture_output=True, check=True
                )
            except subprocess.CalledProcessError as error:
                if error.returncode != 5:  # Not file not found
                    error.add_note(error.stderr.decode())
                    raise

        trash = _trash_darwin


if trash is None:

    def _trash_default(paths: Iterable[os.PathLike[str]]) -> None:
        from tempfile import mkdtemp

        paths_iter = iter(paths)
        first_path = next(paths_iter, None)

        if first_path is None:
            return

        instawowt = make_instawowt()
        parent_folder = mkdtemp(dir=instawowt, prefix=f'deleted-{Path(first_path).name}-')

        for path in chain((first_path,), paths_iter):
            try:
                shutil.move(path, parent_folder)
            except FileNotFoundError:
                pass

    trash = _trash_default
