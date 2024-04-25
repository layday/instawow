from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from itertools import chain
from pathlib import Path
from shutil import move
from tempfile import mkdtemp


def reveal_folder(path: str | os.PathLike[str]) -> None:
    if sys.platform == 'win32':
        os.startfile(path, 'explore')
    else:
        import click

        click.launch(os.fspath(path), locate=True)


def trash(paths: Iterable[Path], *, dest: Path, missing_ok: bool = False) -> None:
    paths_iter = iter(paths)
    first_path = next(paths_iter, None)

    if first_path is None:
        return

    exc_classes = FileNotFoundError if missing_ok else ()

    parent_folder = mkdtemp(dir=dest, prefix=f'deleted-{first_path.name}-')

    for path in chain((first_path,), paths_iter):
        try:
            move(path, parent_folder)
        except exc_classes:
            pass
