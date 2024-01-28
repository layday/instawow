from __future__ import annotations

import posixpath
import zipfile
from collections.abc import Callable, Iterable, Set
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import NamedTuple, Protocol


class ArchiveOpener(Protocol):  # pragma: no cover
    def __call__(self, path: Path) -> AbstractContextManager[Archive]:
        ...


class Archive(NamedTuple):
    top_level_folders: Set[str]
    extract: Callable[[Path], None]


def find_archive_addon_tocs(names: Iterable[str]):
    "Find top-level folders in a list of archive member paths."
    for name in names:
        if name.count(posixpath.sep) == 1:
            head, tail = posixpath.split(name)
            if tail.startswith(head) and tail[-4:].lower() == '.toc':
                yield (name, head)


def make_archive_member_filter_fn(base_dirs: Set[str]):
    "Filter out items which are not sub-paths of top-level folders in an archive."

    def is_subpath(name: str):
        head, sep, _ = name.partition(posixpath.sep)
        return head in base_dirs if sep else False

    return is_subpath


@contextmanager
def open_zip_archive(path: Path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        top_level_folders = {h for _, h in find_archive_addon_tocs(names)}

        def extract(parent: Path) -> None:
            should_extract = make_archive_member_filter_fn(top_level_folders)
            archive.extractall(parent, members=(n for n in names if should_extract(n)))

        yield Archive(top_level_folders, extract)
