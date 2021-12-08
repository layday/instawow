from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence, Set
from datetime import datetime, timedelta
import enum
from functools import partial, wraps
from itertools import chain, repeat
import os
from pathlib import Path, PurePath
import posixpath
from shutil import move as _move
from tempfile import mkdtemp
from typing import Any, Generic, Hashable, TypeVar, overload

_T = TypeVar('_T')
_U = TypeVar('_U')
_H = TypeVar('_H', bound=Hashable)


class StrEnum(str, enum.Enum):
    pass


class TocReader:
    """Extracts key–value pairs from TOC files."""

    def __init__(self, contents: str) -> None:
        self.entries = {
            k: v
            for e in contents.splitlines()
            if e.startswith('##')
            for k, v in (map(str.strip, e.lstrip('#').partition(':')[::2]),)
            if k
        }

    def __getitem__(self, key: str | tuple[str, ...]) -> str | None:
        if isinstance(key, tuple):
            return next(filter(None, map(self.entries.get, key)), None)
        else:
            return self.entries.get(key)

    @classmethod
    def from_addon_path(cls, path: Path, suffix: str = '.toc') -> TocReader:
        return cls((path / (path.name + suffix)).read_text(encoding='utf-8-sig', errors='replace'))


class cached_property(Generic[_T, _U]):
    def __init__(self, f: Callable[[_T], _U]) -> None:
        self.f = f

    @overload
    def __get__(self, o: None, t: type[_T] | None = ...) -> cached_property[_T, _U]:
        ...

    @overload
    def __get__(self, o: _T, t: type[_T] | None = ...) -> _U:
        ...

    def __get__(self, o: _T | None, t: type[_T] | None = None) -> cached_property[_T, _U] | _U:
        if o is None:
            return self
        else:
            o.__dict__[self.f.__name__] = v = self.f(o)
            return v


def bucketise(iterable: Iterable[_U], key: Callable[[_U], _T]) -> defaultdict[_T, list[_U]]:
    "Place the elements of an iterable in a bucket according to ``key``."
    bucket: defaultdict[_T, list[_U]] = defaultdict(list)
    for value in iterable:
        bucket[key(value)].append(value)
    return bucket


def chain_dict(
    keys: Iterable[_T], default: _U, *overrides: Iterable[tuple[_T, _U]]
) -> dict[_T, _U]:
    "Construct a dictionary from a series of two-tuple iterables with overlapping keys."
    return dict(chain(zip(keys, repeat(default)), *overrides))


def uniq(it: Iterable[_H]) -> list[_H]:
    "Deduplicate hashable items in an iterable maintaining insertion order."
    return list(dict.fromkeys(it))


def merge_intersecting_sets(it: Iterable[frozenset[_T]]) -> Iterator[frozenset[_T]]:
    "Recursively merge intersecting sets in a collection."
    many_sets = list(it)
    while many_sets:
        this_set = many_sets.pop(0)
        while True:
            for idx, other_set in enumerate(many_sets):
                if not this_set.isdisjoint(other_set):
                    this_set |= many_sets.pop(idx)
                    break
            else:
                break
        yield this_set


@overload
async def gather(it: Iterable[Awaitable[_U]], wrapper: None = ...) -> list[_U]:
    ...


@overload
async def gather(
    it: Iterable[Awaitable[_U]],
    wrapper: Callable[[Awaitable[_U]], Awaitable[_T]] = ...,
) -> list[_T]:
    ...


async def gather(
    it: Iterable[Awaitable[object]], wrapper: Callable[..., Awaitable[object]] | None = None
) -> Sequence[object]:
    if wrapper is not None:
        it = map(wrapper, it)
    return await asyncio.gather(*it)


@overload
def run_in_thread(
    fn: type[list[object]],
) -> Callable[[Iterable[_U]], Awaitable[list[_U]]]:
    ...


@overload
def run_in_thread(fn: Callable[..., _U]) -> Callable[..., Awaitable[_U]]:
    ...


def run_in_thread(fn: Callable[..., object]) -> Callable[..., Awaitable[object]]:
    @wraps(fn)
    def wrapper(*args: object, **kwargs: object):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(None, partial(fn, *args, **kwargs))

    return wrapper


def tabulate(rows: Sequence[Sequence[object]], *, max_col_width: int = 60) -> str:
    "Produce an ASCII table from equal-length elements in a sequence."
    from textwrap import fill

    def apply_max_col_width(value: object):
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


def move(src: str | os.PathLike[str], dest: str | os.PathLike[str]) -> Any:
    return _move(
        os.fspath(src),  # See https://bugs.python.org/issue32689
        dest,
    )


def trash(paths: Sequence[PurePath], *, dest: PurePath, missing_ok: bool = False) -> None:
    if not paths:
        return

    parent_folder = mkdtemp(dir=dest, prefix=f'deleted-{paths[0].name}-')
    for path in paths:
        try:
            move(path, dest=parent_folder)
        except (FileNotFoundError if missing_ok else ()):
            pass


def shasum(*values: object) -> str:
    "Base-16-encode a string using SHA-256 truncated to 32 characters."
    from hashlib import sha256

    return sha256(''.join(map(str, values)).encode()).hexdigest()[:32]


def is_not_stale(path: Path, ttl: Mapping[str, float]) -> bool:
    "Check if a file is older than ``ttl``."
    return path.exists() and (
        (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)) < timedelta(**ttl)
    )


def find_addon_zip_base_dirs(names: Sequence[str]) -> Iterator[str]:
    "Find top-level folders in a list of ZIP member paths."
    for name in names:
        if name.count(posixpath.sep) == 1:
            head, tail = posixpath.split(name)
            if tail.startswith(head) and tail[-4:].lower() == '.toc':
                yield head


def make_zip_member_filter(base_dirs: Set[str]) -> Callable[[str], bool]:
    "Filter out items which are not sub-paths of top-level folders in a ZIP."

    def is_subpath(name: str):
        head, sep, _ = name.partition(posixpath.sep)
        return head in base_dirs if sep else False

    return is_subpath


def file_uri_to_path(file_uri: str) -> str:
    "Convert a file URI to a path that works both on Windows and *nix."
    from urllib.parse import unquote

    unprefixed_path = unquote(file_uri[7:])  # len('file://')
    # A slash is prepended to the path even when there isn't one there
    # on Windows.  The ``PurePath`` instance will inherit from either
    # ``PurePosixPath`` or ``PureWindowsPath``; this will be a no-op on POSIX.
    if PurePath(unprefixed_path[1:]).drive:
        unprefixed_path = unprefixed_path[1:]
    return unprefixed_path


def normalise_names(replace_delim: str) -> Callable[[str], str]:
    import string

    trans_table = str.maketrans(dict.fromkeys(string.punctuation, ' '))

    def normalise(value: str):
        return replace_delim.join(value.casefold().translate(trans_table).split())

    return normalise
