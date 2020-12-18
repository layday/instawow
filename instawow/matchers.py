from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from functools import total_ordering
import re
from typing import cast

from typing_extensions import TypeAlias

from . import manager
from .models import PkgFolder
from .resolvers import CurseResolver, Defn, InstawowResolver, TukuiResolver, WowiResolver
from .utils import TocReader, bucketise, cached_property, merge_intersecting_sets, uniq

MatchGroups: TypeAlias = 'list[tuple[list[AddonFolder], list[Defn]]]'


_ids_to_sources = {
    'X-Curse-Project-ID': CurseResolver.source,
    'X-Tukui-ProjectID': TukuiResolver.source,
    'X-WoWI-ID': WowiResolver.source,
}
_sources_to_sort_weights = {
    CurseResolver.source: 0,
    TukuiResolver.source: 2,
    WowiResolver.source: 1,
    InstawowResolver.source: 3,
}


@total_ordering
class AddonFolder:
    def __init__(self, name: str, toc_reader: TocReader) -> None:
        self.name = name
        self.toc_reader = toc_reader

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}: {self.name}>'

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (self.__class__, str)):
            return NotImplemented
        return self.name == other

    def __lt__(self, other: object) -> bool:
        if isinstance(other, self.__class__):
            other = other.name
        if not isinstance(other, str):
            return NotImplemented
        return self.name < other

    @cached_property
    def defns_from_toc(self) -> frozenset[Defn]:
        return frozenset(
            Defn(s, i)
            for s, i in ((s, self.toc_reader[k]) for k, s in _ids_to_sources.items())
            if i
        )

    @cached_property
    def version(self) -> str:
        return self.toc_reader['Version', 'X-Packaged-Version', 'X-Curse-Packaged-Version'] or ''


def get_folders(manager: manager.Manager) -> Iterable[AddonFolder]:
    pkg_folders = {f.name for f in manager.database.query(PkgFolder).all()}
    unreconciled_folders = (
        p
        for p in manager.config.addon_dir.iterdir()
        if p.name not in pkg_folders and p.is_dir() and not p.is_symlink()
    )
    suppress_not_found = suppress(FileNotFoundError)
    for folder in unreconciled_folders:
        with suppress_not_found:
            toc_reader = TocReader.from_parent_folder(folder)
            yield AddonFolder(folder.name, toc_reader)


def get_folder_set(manager: manager.Manager) -> frozenset[AddonFolder]:
    return frozenset(get_folders(manager))


async def match_toc_ids(
    manager: manager.Manager, leftovers: frozenset[AddonFolder]
) -> MatchGroups:
    "Attempt to match add-ons from TOC-file source ID entries."

    def bucket_keyer(value: AddonFolder):
        return next(d for d in defns if value.defns_from_toc & d)

    def sort_keyer(value: Defn):
        return _sources_to_sort_weights[value.source]

    matches = [a for a in sorted(leftovers) if a.defns_from_toc]
    defns = list(merge_intersecting_sets(a.defns_from_toc for a in matches))
    return [(f, sorted(b, key=sort_keyer)) for b, f in bucketise(matches, bucket_keyer).items()]


async def match_dir_names(
    manager: manager.Manager, leftovers: frozenset[AddonFolder]
) -> MatchGroups:
    "Attempt to match folders against the master catalogue."

    def bucket_keyer(value: tuple[frozenset[AddonFolder], Defn]):
        return next(f for f in folders if value[0] & f)

    def sort_keyer(value: tuple[frozenset[AddonFolder], Defn]):
        folders, defn = value
        return (-len(folders), _sources_to_sort_weights[defn.source])

    catalogue = await manager.synchronise()

    matches = [
        (
            # We can't use an intersection here because it's not guaranteed
            # to give us ``AddonFolder``s
            frozenset(e for e in leftovers if e in cast('frozenset[AddonFolder]', f)),
            Defn(i.source, i.id),
        )
        for i in catalogue.__root__
        if manager.config.game_flavour in i.game_compatibility
        for f in i.folders
        if f <= leftovers
    ]
    folders = list(merge_intersecting_sets(f for f, _ in matches))
    return [
        (sorted(f), uniq(d for _, d in sorted(b, key=sort_keyer)))
        for f, b in bucketise(matches, bucket_keyer).items()
    ]


async def match_toc_names(
    manager: manager.Manager, leftovers: frozenset[AddonFolder]
) -> MatchGroups:
    "Attempt to match add-ons from TOC-file name entries."

    def normalise(value: str):
        return re.sub(r'[^0-9A-Za-z]', '', value.casefold())

    catalogue = await manager.synchronise()

    norm_to_items = bucketise(catalogue.__root__, key=lambda i: normalise(i.name))
    matches = ((e, norm_to_items.get(normalise(e.name))) for e in sorted(leftovers))
    return [([e], uniq(Defn(i.source, i.id) for i in m)) for e, m in matches if m]
