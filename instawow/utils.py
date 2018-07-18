
from collections import namedtuple
import io
from pathlib import Path
import re
import typing as T
import zipfile


class ExtractConflict(Exception):

    def __init__(self, conflicting_folders):
        super().__init__()
        self.conflicting_folders = conflicting_folders


class Archive:

    ExtractConflict = ExtractConflict

    def __init__(self, payload: bytes):
        self._archive = zipfile.ZipFile(io.BytesIO(payload))

    def extract(self, parent_folder: Path, *,
                overwrite: T.Union[bool, T.Set[str]]=False) -> None:
        "Extract the archive contents under ``parent_folder``."
        if overwrite is not True:
            conflicts = ({f.name for f in self.root_folders} &
                         ({f.name for f in parent_folder.iterdir()} -
                          (overwrite or set())))
            if conflicts:
                raise ExtractConflict(conflicts)
        self._archive.extractall(parent_folder)

    @property
    def root_folders(self) -> T.List[Path]:
        folders = sorted({Path(p).parts[0] for p in self._archive.namelist()})
        folders = [Path(p) for p in folders]
        return folders


_TocEntry = namedtuple('_TocEntry', 'key value')

class TocReader:
    """Extracts key–value pairs from TOC files."""

    def __init__(self, toc_file_path: Path):
        entries = (e.lstrip('# ').partition(': ')
                   for e in toc_file_path.read_text(encoding='utf-8-sig').splitlines()
                   if e.startswith('## '))
        entries = {e[0]: e[2] for e in entries}
        self.entries = entries

    def __getitem__(self, key: T.Union[str, T.Tuple[str]]) -> _TocEntry:
        if isinstance(key, tuple):
            try:
                return next(filter(lambda i: i.value,
                                   (self.__getitem__(k) for k in key)))
            except StopIteration:
                key = key[0]
        return _TocEntry(key, self.entries.get(key))


def slugify(text: str, *,
            _re_lc=re.compile(r'[^0-9a-z ]')) -> str:
    "Convert an add-on name into a lower-alphanumeric slug."
    return '-'.join(_re_lc.sub(' ', text.casefold()).split())
