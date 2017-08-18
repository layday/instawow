
from collections import OrderedDict, namedtuple
from functools import reduce
import io
from pathlib import Path
from textwrap import fill
import typing
import zipfile


class _ExtractConflict(Exception):
    pass


class Archive:

    ExtractConflict = _ExtractConflict

    def __init__(self, payload: bytes):
        self._archive = zipfile.ZipFile(io.BytesIO(payload))

    @property
    def members(self) -> typing.Set[str]:
        return {i.partition('/')[0] for i in self._archive.namelist()}

    def extract(self, parent_folder: Path, *, overwrite: bool=False):
        if not overwrite:
            conflicting_folders = self.members & {f.name for f in
                                                  parent_folder.iterdir()}
            if conflicting_folders:
                raise _ExtractConflict(conflicting_folders)
        self._archive.extractall(parent_folder)


class TocReader:
    """Extracts key–value pairs from TOC files."""

    _TocEntry = namedtuple('_TocEntry', 'key value')

    def __init__(self, toc_file_path: Path):
        entries = (e.lstrip('# ').partition(': ')
                   for e in toc_file_path.read_text().splitlines()
                   if e.startswith('## '))
        entries = ((e[0], e[2]) for e in entries)
        self.entries = OrderedDict(entries)

    def __getitem__(self, keys: typing.Union[str, typing.Tuple[str]]) \
            -> '[_TocEntry]':
        if isinstance(keys, tuple):
            return next(filter(lambda i: i.value,
                               (self.__getitem__(k) for k in keys)),
                        self.__getitem__(keys[0]))
        return self._TocEntry(keys, self.entries.get(keys))


def format_columns(pkg, columns):
    def _parse_field(name, value):
        if name == 'folders':
            value = '\n'.join(f.path.name for f in value)
        elif name == 'description':
            value = fill(value, width=40)
        return value
    return (_parse_field(c, reduce(getattr, [pkg] + c.split('.')))
            for c in columns)
