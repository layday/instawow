from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial
from itertools import chain, repeat
from pathlib import Path
import re
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Hashable,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

try:
    from typing import Literal as _Literal
except ImportError:
    from typing_extensions import Literal as _Literal
Literal = _Literal  # ...

if TYPE_CHECKING:
    from prompt_toolkit.shortcuts import ProgressBar

    from .manager import CliManager

    _H = TypeVar('_H', bound=Hashable)
    _AnySet = TypeVar('_AnySet', bound=AbstractSet)
_V = TypeVar('_V')


class ManagerAttrAccessMixin:
    def __getattr__(self, name: str) -> Any:
        return getattr(self.manager, name)


class _TocEntry(NamedTuple):
    key: str
    value: str

    def __bool__(self) -> bool:
        return bool(self.value)


class TocReader:
    """Extracts key–value pairs from TOC files."""

    def __init__(self, contents: str) -> None:
        possible_entries = (
            map(str.strip, e.lstrip('#').partition(':')[::2])
            for e in contents.splitlines()
            if e.startswith('##')
        )
        self.entries = {k: v for k, v in possible_entries if k}
        self.default = ''

    def __getitem__(self, key: Union[str, Tuple[str, ...]]) -> _TocEntry:
        if isinstance(key, tuple):
            try:
                return next(filter(None, (self[k] for k in key)))
            except StopIteration:
                key = key[0]
        return _TocEntry(key, self.entries.get(key, self.default))

    @classmethod
    def from_path(cls, path: Path) -> TocReader:
        return cls(path.read_text(encoding='utf-8-sig', errors='replace'))

    @classmethod
    def from_path_name(cls, path: Path) -> TocReader:
        return cls.from_path(path / f'{path.name}.toc')


class cached_property(Generic[_V]):
    def __init__(self, f: Callable[[Any], _V]) -> None:
        self.f = f

    @overload
    def __get__(self, o: None, t: Optional[type] = None) -> cached_property[_V]:
        ...

    @overload
    def __get__(self, o: Any, t: Optional[type] = None) -> _V:
        ...

    def __get__(self, o: Any, t: Optional[type] = None) -> Union[cached_property[_V], _V]:
        if o is None:
            return self.f
        else:
            o.__dict__[self.f.__name__] = v = self.f(o)
            return v


def bucketise(iterable: Iterable[_V], key: Callable[[_V], _H] = lambda v: v) -> Dict[_H, List[_V]]:
    "Place the elements of an iterable in a bucket according to ``key``."
    bucket: Any = defaultdict(list)
    for value in iterable:
        bucket[key(value)].append(value)
    return bucket


def dict_chain(
    keys: Iterable[_H], default: Any, *overrides: Iterable[Tuple[_H, Any]]
) -> Dict[_H, Any]:
    "Construct a dictionary from a series of iterables with overlapping keys."
    return dict(chain(zip(keys, repeat(default)), *overrides))


def uniq(it: Iterable[_H]) -> List[_H]:
    "Deduplicate hashable items in an iterable maintaining insertion order."
    return list(dict.fromkeys(it))


def merge_intersecting_sets(it: Iterable[_AnySet]) -> Iterable[_AnySet]:
    "Recursively merge intersecting sets in a collection."
    many_sets = deque(it)
    while True:
        try:
            this_set = many_sets.popleft()
        except IndexError:
            return
        while True:
            for other_set in many_sets:
                if this_set & other_set:
                    # The in-place operator will mutate unfrozen sets
                    # in the original collection
                    this_set = this_set | other_set  # type: ignore
                    many_sets.remove(other_set)
                    break
            else:
                break
        yield this_set


async def gather(it: Iterable[Awaitable[_V]], return_exceptions: bool = True) -> List[_V]:
    return await asyncio.gather(*it, return_exceptions=return_exceptions)


def run_in_thread(fn: Callable[..., _V]) -> Callable[..., Awaitable[_V]]:
    return lambda *a, **k: asyncio.get_running_loop().run_in_executor(None, lambda: fn(*a, **k))


@contextmanager
def copy_resources(*packages: str) -> Iterator[Path]:
    """Copy package resources to a temporary directory on disk.

    Alembic cannot construct a migration environment from memory.
    This is a genericised bodge to make migrations work in a frozen instawow.
    """
    from importlib.resources import contents, is_resource, read_binary
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for package in packages:
            for resource in filter(partial(is_resource, package), contents(package)):
                parent_dir = tmp_path.joinpath(*package.split('.'))
                if not parent_dir.is_dir():
                    parent_dir.mkdir(parents=True)

                filename = parent_dir / resource
                # PyOxidizer does not expose Python source files to `importlib`
                # (see https://github.com/indygreg/PyOxidizer/issues/237).
                # Migrations have a "null" extension added to them that is shorn
                # from the extracted filename
                if filename.suffix == '.0':
                    filename = filename.with_suffix('')
                filename.write_bytes(read_binary(package, resource))
        yield tmp_path


def slugify(text: str) -> str:
    "Convert an add-on name into a lower-alphanumeric slug."
    return '-'.join(re.sub(r'[^0-9a-z]', ' ', text.casefold()).split())


def tabulate(rows: Sequence[Sequence[Any]], *, max_col_width: int = 60) -> str:
    "Produce an ASCII table from equal-length elements in a sequence."
    from textwrap import fill

    def apply_max_col_width(value: Sequence[Any]):
        return fill(str(value), width=max_col_width, max_lines=1)

    def calc_resultant_col_widths(rows: Sequence[Sequence[str]]):
        cols = zip(*rows)
        return [max(map(len, c)) for c in cols]

    rows = [tuple(map(apply_max_col_width, r)) for r in rows]
    head, *tail = rows

    base_template = ' '.join(f'{{{{{{0}}{w}}}}}' for w in calc_resultant_col_widths(rows))
    row_template = base_template.format(':<')
    table = '\n'.join(
        (
            base_template.format(':^').format(*head),
            base_template.format(f'0:-<').format(''),
            *(row_template.format(*r) for r in tail),
        )
    )
    return table


def make_progress_bar(**kwargs: Any) -> ProgressBar:
    "A ``ProgressBar`` with download progress expressed in megabytes."
    import signal

    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts.progress_bar import ProgressBar, formatters
    from prompt_toolkit.utils import Event

    # There is a race condition in the bar's shutdown logic
    # where the bar-drawing thread is left to run indefinitely
    # if the prompt_toolkit app is not (yet) running
    # but is scheduled to run when ``__exit__``ing the bar.
    # If an exception occurs early in the execution cycle or if execution
    # finishes before prompt_toolkit is able to crank the app,
    # instawow will hang.  This is my ham-fisted attempt to work
    # around all that by signalling to the daemon thread to kill the app.

    class PatchedProgressBar(ProgressBar):
        def __exit__(self, *args: Any):
            if self._has_sigwinch:
                self._loop.add_signal_handler(
                    signal.SIGWINCH, self._previous_winch_handler  # type: ignore
                )

            if self._thread is not None:

                def attempt_exit(sender: Any):
                    sender.is_running and sender.exit()

                # Signal to ``_auto_refresh_context`` that it should exit the app
                self.app.on_invalidate = Event(self.app, attempt_exit)
                self._thread.join()

    class DownloadProgress(formatters.Progress):
        template = formatters.Progress.template + 'MB'

        def format(self, progress_bar: ProgressBar, progress: Any, width: int):
            def format_pct(value: int) -> str:
                return f'{value / 2 ** 20:.1f}'

            return HTML(self.template).format(
                current=format_pct(progress.items_completed), total=format_pct(progress.total)
            )

    f = [
        formatters.Label(),
        formatters.Text(' '),
        formatters.Percentage(),
        formatters.Text(' '),
        formatters.Bar(),
        formatters.Text(' '),
        DownloadProgress(),
        formatters.Text(' '),
        formatters.Text('eta [', style='class:time-left'),
        formatters.TimeLeft(),
        formatters.Text(']', style='class:time-left'),
        formatters.Text(' '),
    ]
    progress_bar = PatchedProgressBar(formatters=f, **kwargs)
    return progress_bar


def shasum(*values: str) -> str:
    "Base-16-encode a string using SHA-256 truncated to 32 characters."
    from hashlib import sha256

    return sha256(''.join(values).encode()).hexdigest()[:32]


def is_not_stale(path: Path, ttl: int, unit: str = 'seconds') -> bool:
    "Check if a file is older than ``ttl``."
    mtime = path.exists() and path.stat().st_mtime
    return mtime > 0 and (
        (datetime.now() - datetime.fromtimestamp(cast(float, mtime))) < timedelta(**{unit: ttl})
    )


def get_version() -> str:
    "Get the installed version of instawow."
    try:
        from ._version import __version__
    except ImportError:
        return 'dev'
    else:
        return __version__


def is_outdated(manager: CliManager) -> bool:
    """Check on PyPI to see if the installed instawow is outdated.

    The response is cached for 24 hours.
    """
    __version__ = get_version()
    if 'dev' in __version__:
        return False

    def parse_version(version: str) -> Tuple[int, ...]:
        return tuple(map(int, version.split('.')[:3]))

    cache_file = manager.config.temp_dir / '.pypi_version'
    if is_not_stale(cache_file, 1, 'days'):
        version = cache_file.read_text(encoding='utf-8')
    else:
        from aiohttp.client import ClientError

        async def get_metadata():
            api_url = 'https://pypi.org/pypi/instawow/json'
            async with manager.web_client.get(api_url) as response:
                return await response.json()

        try:
            version = manager.run(get_metadata())['info']['version']
        except ClientError:
            version = __version__
        else:
            cache_file.write_text(version, encoding='utf-8')

    return parse_version(version) > parse_version(__version__)


def setup_logging(logger_dir: Path, level: Union[int, str] = 'INFO') -> int:
    from loguru import logger

    handler = {
        'sink': logger_dir / 'error.log',
        'level': level,
        'rotation': '1 MB',
        'enqueue': True,
    }
    (handler_id,) = logger.configure(handlers=(handler,))
    return handler_id
