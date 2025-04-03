from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Iterator, Set
from itertools import chain, groupby, islice, repeat
from weakref import WeakValueDictionary


class WeakValueDefaultDictionary[T, U](WeakValueDictionary[T, U]):
    def __init__(self, default_factory: Callable[[], U]) -> None:
        super().__init__()
        self.__default_factory = default_factory

    def __getitem__(self, key: T) -> U:
        try:
            return super().__getitem__(key)
        except KeyError:
            default = self[key] = self.__default_factory()
            return default


def all_eq(it: Iterable[object]) -> bool:
    "Check that all elements of an iterable are equal."
    groups = groupby(it)
    return next(groups, True) and not next(groups, False)


def bucketise[T, U](iterable: Iterable[U], key: Callable[[U], T]) -> dict[T, list[U]]:
    "Place the elements of an iterable in a bucket according to ``key``."
    bucket = dict[T, list[U]]()
    for value in iterable:
        bucket.setdefault(key(value), []).append(value)

    return bucket


def fill[T](it: Iterable[T], fill: T, length: int) -> Iterable[T]:
    "Fill an iterable of specified length."
    return islice(chain(it, repeat(fill)), 0, length)


def merge_intersecting_sets[T](it: Iterable[Set[T]]) -> Iterator[frozenset[T]]:
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


def uniq[HashableT: Hashable](it: Iterable[HashableT]) -> list[HashableT]:
    "Deduplicate hashable items in an iterable maintaining insertion order."
    return list(dict.fromkeys(it))
