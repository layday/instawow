
from collections import namedtuple
from pathlib import Path
import re
import typing as T


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
