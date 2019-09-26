from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from functools import partial, reduce
from itertools import repeat
from pathlib import Path
import re
from typing import TYPE_CHECKING
from typing import (Any, Awaitable, Callable, Iterable, List, NamedTuple,
                    Optional, Tuple, Type, TypeVar, Union)

try:
    from typing import Literal      # type: ignore
except ImportError:
    from typing_extensions import Literal

if TYPE_CHECKING:
    import prompt_toolkit.shortcuts.progress_bar.base as pbb

    from .config import Config
    from .manager import CliManager


class ManagerAttrAccessMixin:

    def __getattr__(self, name: str) -> Any:
        return getattr(self.manager, name)


class _TocEntry(NamedTuple):

    key: str
    value: Optional[str]

    def __bool__(self) -> bool:
        return bool(self.value)


class TocReader:
    """Extracts key–value pairs from TOC files."""

    def __init__(self, contents: str, default: Literal[None, ''] = '') -> None:
        possible_entries = (map(str.strip, e.lstrip('#').partition(':')[::2])
                            for e in contents.splitlines()
                            if e.startswith('##'))
        self.entries = {k: v for k, v in possible_entries if k}
        self.default = default

    def __getitem__(self, key: Union[str, Tuple[str, ...]]) -> _TocEntry:
        if isinstance(key, tuple):
            try:
                return next(filter(lambda i: i.value, (self[k] for k in key)))
            except StopIteration:
                key = key[0]
        return _TocEntry(key, self.entries.get(key, self.default))

    @classmethod
    def from_path(cls, path: Path, *args: Any, **kwargs: Any) -> TocReader:
        return cls(path.read_text(encoding='utf-8-sig'), *args, **kwargs)

    @classmethod
    def from_path_name(cls, path: Path, *args: Any, **kwargs: Any) -> TocReader:
        return cls.from_path(path / f'{path.name}.toc', *args, **kwargs)


O = TypeVar('O')


class cached_property:

    def __init__(self, f: Callable) -> None:
        self.f = f

    def __get__(self, o: Optional[O], t: Type[O]) -> Any:
        if o is None:
            return self.f
        else:
            o.__dict__[self.f.__name__] = v = self.f(o)
            return v


def bucketise(iterable: Iterable, key: Callable = (lambda v: v)) -> defaultdict:
    "Place the elements of ``iterable`` into a bucket according to ``key``."
    bucket = defaultdict(list)      # type: ignore
    for value in iterable:
        bucket[key(value)].append(value)
    return bucket


def dict_merge(*args: dict) -> dict:
    "Right merge any number of ``dict``s."
    return reduce(lambda p, n: {**p, **n}, args, {})


def iter_or_repeat(value: Any) -> Iterable:
    "Repeat ``value`` if it is not iterable."
    try:
        return iter(value)
    except TypeError:
        return repeat(value)


async def gather(it: Iterable, return_exceptions: bool = True) -> List[Any]:
    return await asyncio.gather(*it, return_exceptions=return_exceptions)


def run_in_thread(fn: Callable) -> Callable[..., Awaitable]:
    return lambda *a, **k: asyncio.get_running_loop().run_in_executor(None, partial(fn, *a, **k))


_match_loweralphanum = re.compile(r'[^0-9a-z ]')


def slugify(text: str) -> str:
    "Convert an add-on name into a lower-alphanumeric slug."
    return '-'.join(_match_loweralphanum.sub(' ', text.casefold()).split())


_match_bbcode = re.compile(r'''
(\[(?:(?:font
        |size
        |color
        |list
        |url
        |email
        |highlight)="[^"]*"
     |(?:b
        |i
        |u
        |left
        |center
        |right
        |list
        |\*
        |url
        |quote
        |code))\]
 |\[/(?:font
       |size
       |color
       |b
       |i
       |u
       |left
       |center
       |right
       |list
       |list
       |url
       |email
       |quote
       |code
       |highlight)\]
|\[img\][^\[]*\[/img\])
''', re.IGNORECASE | re.VERBOSE)


def bbegone(text: str) -> str:
    "Naïvely remove BBCode from package descriptions."
    return _match_bbcode.sub('', text).strip()


def make_progress_bar(**kwargs: Any) -> pbb.ProgressBar:
    "A ``ProgressBar`` with download progress expressed in megabytes."
    from contextlib import contextmanager
    from prompt_toolkit.formatted_text import HTML
    import prompt_toolkit.shortcuts.progress_bar.base as pbb
    from prompt_toolkit.shortcuts.progress_bar import formatters

    # There is a race condition in the bar's shutdown logic
    # where the bar-drawing thread is left to run indefinitely
    # if the prompt_toolkit app is not (yet) running
    # but is scheduled to run when ``__exit__``ing the bar.
    # If an exception occurs early in the execution cycle or if execution
    # finishes before prompt_toolkit is able to crank the app,
    # instawow will hang.  This is my ham-fisted attempt to work
    # around all that by relocating the ``.exit()`` call.  The progress bar
    # 'signals' to the thread that the app is ready to exit
    # and the app is exited from inside the thread.
    # To avoid having to monkey-patch ``run`` which is nested
    # inside ``__enter__``, we overwrite ``pbb._auto_refresh_context``.

    class ProgressBar(pbb.ProgressBar):
        def __exit__(self, *args):
            if self._has_sigwinch:
                self._loop.add_signal_handler(pbb.signal.SIGWINCH, self._previous_winch_handler)

            # Signal to ``_auto_refresh_context`` that it should exit the app
            self.app._should_exit = True
            self._thread.join()
            del self.app._should_exit

    _bar_refresh_interval = .1

    @contextmanager
    def _auto_refresh_context(app, _refresh_interval=None):
        done = [False]

        def run():
            while not done[0]:
                pbb.time.sleep(_bar_refresh_interval)
                app.invalidate()
                if getattr(app, '_should_exit', False) and app.is_running:
                    app.exit()

        t = pbb.threading.Thread(target=run)
        t.daemon = True
        t.start()

        try:
            yield
        finally:
            done[0] = True

    pbb._auto_refresh_context = _auto_refresh_context

    class ProgressInMB(formatters.Progress):
        template = f'{formatters.Progress.template}MB'

        def format(self, _bar, counter, _width):
            html = HTML(self.template)
            return html.format(**{f: f'{getattr(counter, f) / 2 ** 20:.1f}'
                                  for f in ('current', 'total')})

    formatters = [formatters.Label(),
                  formatters.Text(' '),
                  formatters.Percentage(),
                  formatters.Text(' '),
                  formatters.Bar(),
                  formatters.Text(' '),
                  ProgressInMB(),
                  formatters.Text(' '),
                  formatters.Text('eta [', style='class:time-left'),
                  formatters.TimeLeft(),
                  formatters.Text(']', style='class:time-left'),
                  formatters.Text(' '),]
    progress_bar = ProgressBar(formatters=formatters, **kwargs)
    return progress_bar


def is_not_stale(path: Path, ttl: int, unit: str = 'seconds') -> bool:
    "Check if a file is older than ``ttl``."
    mtime = path.exists() and path.stat().st_mtime
    return mtime > 0 and (datetime.now() - datetime.fromtimestamp(mtime)) < timedelta(**{unit: ttl})


def is_outdated(manager: CliManager) -> bool:
    """Check against PyPI to see if `instawow` is outdated.

    The response is cached for 24 hours.
    """
    from . import __version__

    def parse_version(version: str) -> Tuple[int, ...]:
        return tuple(map(int, version.split('.')[:3]))

    cache_file = manager.config.config_dir / '.pypi_version'
    if is_not_stale(cache_file, 1, 'days'):
        version = cache_file.read_text(encoding='utf-8')
    else:
        from aiohttp.client import ClientError

        async def get_metadata() -> dict:
            url = 'https://pypi.org/pypi/instawow/json'
            async with manager.web_client.get(url) as response:
                return await response.json()

        try:
            version = manager.run(get_metadata())['info']['version']
        except ClientError:
            version = __version__
        else:
            cache_file.write_text(version, encoding='utf-8')

    # Installed version > version on PyPI if running in dev or
    # user upgraded without being prompted
    if parse_version(__version__) > parse_version(version):
        return False
    else:
        return __version__ != version


def setup_logging(config: Config, level: Union[int, str] = 'INFO') -> int:
    from loguru import logger

    handler = {'sink': config.logger_dir / 'error.log',
               'level': level,
               'rotation': '1 MB',
               'enqueue': True}
    handler_id, = logger.configure(handlers=(handler,))
    return handler_id
