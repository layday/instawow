from __future__ import annotations

import sys
from collections.abc import Callable, Hashable, Iterable, Iterator, Set
from itertools import chain, groupby, islice, repeat
from typing import TypeVar
from weakref import WeakValueDictionary

_T = TypeVar('_T')
_U = TypeVar('_U')
_THashable = TypeVar('_THashable', bound=Hashable)


class WeakValueDefaultDictionary(WeakValueDictionary[_T, _U]):
    def __init__(self, default_factory: Callable[[], _U]) -> None:
        super().__init__()
        self.__default_factory = default_factory

    def __getitem__(self, key: _T) -> _U:
        try:
            return super().__getitem__(key)
        except KeyError:
            default = self[key] = self.__default_factory()
            return default


def all_eq(it: Iterable[object]) -> bool:
    "Check that all elements of an iterable are equal."
    groups = groupby(it)
    return next(groups, True) and not next(groups, False)


if sys.version_info >= (3, 12):
    from itertools import batched as batched
else:

    def batched(iterable: Iterable[_T], n: int) -> Iterator[tuple[_T, ...]]:  # pragma: no cover
        # batched('ABCDEFG', 3) → ABC DEF G
        if n < 1:
            raise ValueError('n must be at least one')
        it = iter(iterable)
        while batch := tuple(islice(it, n)):
            yield batch


def bucketise(iterable: Iterable[_U], key: Callable[[_U], _T]) -> dict[_T, list[_U]]:
    "Place the elements of an iterable in a bucket according to ``key``."
    bucket = dict[_T, list[_U]]()
    for value in iterable:
        bucket.setdefault(key(value), []).append(value)

    return bucket


def fill(it: Iterable[_T], fill: _T, length: int) -> Iterable[_T]:
    "Fill an iterable of specified length."
    return islice(chain(it, repeat(fill)), 0, length)


def merge_intersecting_sets(it: Iterable[Set[_T]]) -> Iterator[frozenset[_T]]:
    "Recursively merge intersecting sets in a collection."
    many_sets = list(map(frozenset, it))
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


def uniq(it: Iterable[_THashable]) -> list[_THashable]:
    "Deduplicate hashable items in an iterable maintaining insertion order."
    return list(dict.fromkeys(it))
