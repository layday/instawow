
from collections import namedtuple
from datetime import datetime
from pathlib import Path
import re
import typing as T

from . import __version__


__all__ = ('TocReader', 'slugify', 'is_outdated')


class TocReader:
    """Extracts key–value pairs from TOC files."""

    Entry = namedtuple('_TocEntry', 'key value')

    def __init__(self, path: Path) -> None:
        entries = (e.lstrip('# ').partition(': ')[::2]
                   for e in path.read_text(encoding='utf-8-sig').splitlines()
                   if e.startswith('## '))
        self.entries = dict(entries)

    def __getitem__(self, key: T.Union[str, T.Tuple[str]]) -> Entry:
        if isinstance(key, tuple):
            try:
                return next(filter(lambda i: i.value,
                                   (self.__getitem__(k) for k in key)))
            except StopIteration:
                key = key[0]
        return self.Entry(key, self.entries.get(key))


def slugify(text: str, *,
            _re_lc=re.compile(r'[^0-9a-z ]')) -> str:
    "Convert an add-on name into a lower-alphanumeric slug."
    return '-'.join(_re_lc.sub(' ', text.casefold()).split())


def is_outdated(manager) -> bool:
    """Check against PyPI to see if `instawow` is outdated.

    The response is cached for 24 hours.
    """
    def parse_version(version):
        return tuple(map(int, version.split('.')))

    cache_file = manager.config.config_dir/'.pypi_version'
    if cache_file.exists() and \
            (datetime.now() -
             datetime.fromtimestamp(cache_file.stat().st_mtime)).days < 1:
        version = cache_file.read_text(encoding='utf-8')
    else:
        from aiohttp.client import ClientError

        async def get_metadata():
            async with (await manager.client_factory()) as session, \
                       session.get('https://pypi.org/pypi/instawow/json') as response:
                return await response.json()

        try:
            version = manager.loop.run_until_complete(get_metadata())['info']['version']
        except ClientError:
            version = __version__
        else:
            cache_file.write_text(version, encoding='utf-8')
    # Make ``False``` if installed version is greater than version
    # from PyPI (cache is stale)
    if parse_version(__version__) > parse_version(version):
        version = __version__
    return __version__ != version
