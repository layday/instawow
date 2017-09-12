
from collections import namedtuple
import io
import os
from pathlib import Path
import typing
import zipfile

from click._termui_impl import ProgressBar as _ProgressBar, \
                               BEFORE_BAR, AFTER_BAR


class ExtractConflict(Exception):

    def __init__(self, conflicting_folders):
        super().__init__()
        self.conflicting_folders = conflicting_folders


class Archive:

    ExtractConflict = ExtractConflict

    def __init__(self,
                 payload: bytes):
        self._archive = zipfile.ZipFile(io.BytesIO(payload))

    def extract(self,
                parent_folder: Path,
                *,
                overwrite: typing.Union[bool, typing.Set[str]]=False):
        if overwrite is not True:
            conflicting_folders = \
                ({Path(p).parts[0] for p in self._archive.namelist()} &
                 ({f.name for f in parent_folder.iterdir()} -
                  (overwrite or set())))
            if conflicting_folders:
                raise ExtractConflict(conflicting_folders)
        self._archive.extractall(parent_folder)


_TocEntry = namedtuple('_TocEntry', 'key value')

class TocReader:
    """Extracts key–value pairs from TOC files."""

    def __init__(self,
                 toc_file_path: Path):
        entries = (e.lstrip('# ').partition(': ')
                   for e in toc_file_path.read_text().splitlines()
                   if e.startswith('## '))
        entries = {e[0]: e[2] for e in entries}
        self.entries = entries

    def __getitem__(self,
                    keys: typing.Union[str, typing.Tuple[str]]) -> _TocEntry:
        if isinstance(keys, tuple):
            try:
                return next(filter(lambda i: i.value,
                                   (self.__getitem__(k) for k in keys)))
            except StopIteration:
                keys = keys[0]
        return _TocEntry(keys, self.entries.get(keys))


class ProgressBar(_ProgressBar):
    """A `ProgressBar` subclass that clears its output upon completion."""

    def __init__(self, **kwargs):
        super().__init__(**{'iterable': None,
                            'bar_template': '[%(bar)s]  %(info)s',
                            **kwargs})

    def render_finish(self) -> None:
        if self.is_hidden:
            return

        self.file.write(BEFORE_BAR + (' ' * self.max_width) + AFTER_BAR +
                        ('' if os.name == 'nt' else '\x1b[A'))
        self.file.flush()
