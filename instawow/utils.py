from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial, wraps
from itertools import chain, repeat, takewhile
from pathlib import Path, PurePath
import posixpath
import re
from shutil import move as _move
from tempfile import mkdtemp
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    DefaultDict,
    Dict,
    Generic,
    Hashable,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

from typing_extensions import Literal

if TYPE_CHECKING:
    from prompt_toolkit.shortcuts import ProgressBar

    _H = TypeVar('_H', bound=Hashable)
    _AnySet = TypeVar('_AnySet', bound=AbstractSet)


_V = TypeVar('_V')


class _TocEntry(NamedTuple):
    key: str
    value: str

    def __bool__(self) -> bool:
        return bool(self.value)


class TocReader:
    """Extracts key–value pairs from TOC files."""

    default = ''

    def __init__(self, contents: str) -> None:
        possible_entries = (
            map(str.strip, e.lstrip('#').partition(':')[::2])
            for e in contents.splitlines()
            if e.startswith('##')
        )
        self.entries = {k: v for k, v in possible_entries if k}

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
    def from_parent_folder(cls, path: Path) -> TocReader:
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
            return self
        else:
            o.__dict__[self.f.__name__] = v = self.f(o)
            return v


def bucketise(iterable: Iterable[_V], key: Callable[[_V], _H]) -> DefaultDict[_H, List[_V]]:
    "Place the elements of an iterable in a bucket according to ``key``."
    bucket: Any = defaultdict(list)
    for value in iterable:
        bucket[key(value)].append(value)
    return bucket


def chain_dict(
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
                    # The in-place operator would mutate unfrozen sets
                    # in the original collection
                    this_set = this_set | other_set  # type: ignore
                    many_sets.remove(other_set)
                    break
            else:
                break
        yield this_set


@overload
async def gather(
    it: Iterable[Awaitable[_V]], return_exceptions: Literal[True] = ...
) -> List[Union[BaseException, _V]]:
    ...


@overload
async def gather(it: Iterable[Awaitable[_V]], return_exceptions: Literal[False] = ...) -> List[_V]:
    ...


async def gather(
    it: Iterable[Awaitable[_V]], return_exceptions: bool = True
) -> Union[List[Union[BaseException, _V]], List[_V]]:
    return await asyncio.gather(*it, return_exceptions=return_exceptions)


def run_in_thread(fn: Callable[..., _V]) -> Callable[..., Awaitable[_V]]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    return wrapper


class _StopIteration(Exception):
    pass


def _iit_next(it: Iterator[_V]) -> _V:
    try:
        return next(it)
    except StopIteration:
        raise _StopIteration


# From Starlette: https://github.com/encode/starlette/blob/78f7095/starlette/concurrency.py
async def iter_in_thread(it: Iterator[_V]) -> AsyncIterator[_V]:
    loop = asyncio.get_running_loop()
    while True:
        try:
            yield await loop.run_in_executor(None, _iit_next, it)
        except _StopIteration:
            return


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
                # The filenames of Python files have a secondary ".0" extension
                # so that PyOx will regard them as binary resources.
                # The extension is then removed when they're copied into
                # the temporary folder
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

    base_template = '  '.join(f'{{{{{{0}}{w}}}}}' for w in calc_resultant_col_widths(rows))
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

    _SIGWINCH = getattr(signal, "SIGWINCH", None)

    class PatchedProgressBar(ProgressBar):
        def __exit__(self, *args: Any):
            if self._has_sigwinch:
                self._loop.remove_signal_handler(_SIGWINCH)
                signal.signal(_SIGWINCH, self._previous_winch_handler)

            if self._thread is not None:

                def attempt_exit(sender: Any):
                    sender.is_running and sender.exit()

                # Signal to ``_auto_refresh_context`` that it should exit the app
                self.app.on_invalidate = Event(self.app, attempt_exit)
                self._thread.join()

            self._app_loop.close()

    class DownloadProgress(formatters.Progress):
        template = formatters.Progress.template + 'MB'

        def format(self, progress_bar: ProgressBar, progress: Any, width: int):
            def format_pct(value: int) -> str:
                return f'{value / 2 ** 20:.1f}'

            return HTML(self.template).format(
                current=format_pct(progress.items_completed),
                total=format_pct(progress.total) if progress.total else '?',
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


def move(src: PurePath, dst: PurePath) -> PurePath:
    # See https://bugs.python.org/issue32689
    return _move(str(src), dst)


def trash(paths: Sequence[PurePath], *, dst: PurePath, missing_ok: bool = False) -> None:
    parent_folder = Path(mkdtemp(dir=dst, prefix=f'deleted-{paths[0].name}-'))
    for path in paths:
        try:
            move(path, dst=parent_folder)
        except (FileNotFoundError if missing_ok else ()):
            pass


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


def is_outdated() -> Tuple[bool, str]:
    """Check on PyPI to see if the installed copy of instawow is outdated.

    The response is cached for 24 hours.
    """
    __version__ = get_version()
    if 'dev' in __version__:
        return (False, '')

    from aiohttp.client import ClientError

    from .config import Config
    from .manager import init_web_client

    def parse_version(version: str) -> Tuple[int, ...]:
        version_numbers = version.split('.')[:3]
        int_only_version_numbers = (
            int(''.join(takewhile('0123456789'.__contains__, e))) for e in version_numbers
        )
        return tuple(int_only_version_numbers)

    dummy_config = Config.get_dummy_config()
    if not dummy_config.auto_update_check:
        return (False, '')

    cache_file = dummy_config.temp_dir / '.pypi_version'
    if is_not_stale(cache_file, 1, 'days'):
        version = cache_file.read_text(encoding='utf-8')
    else:

        async def get_metadata():
            api_url = 'https://pypi.org/pypi/instawow/json'
            async with init_web_client() as web_client, web_client.get(api_url) as response:
                return await response.json()

        loop = asyncio.new_event_loop()
        try:
            version = loop.run_until_complete(get_metadata())['info']['version']
        except ClientError:
            version = __version__
        else:
            cache_file.write_text(version, encoding='utf-8')
        finally:
            loop.close()

    return (parse_version(version) > parse_version(__version__), version)


def find_zip_base_dirs(names: Sequence[str]) -> Set[str]:
    "Find top-level folders in a list of ZIP member paths."
    return {n for n in (posixpath.dirname(n) for n in names) if n and posixpath.sep not in n}


def make_zip_member_filter(base_dirs: Set[str]) -> Callable[[str], bool]:
    """Filter out items which are not sub-paths of top-level folders for the
    purpose of extracting ZIP files.
    """

    def is_subpath(name: str):
        head, sep, _ = name.partition(posixpath.sep)
        return cast(bool, sep) and head in base_dirs

    return is_subpath
