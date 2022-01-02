from __future__ import annotations

from functools import total_ordering
from pathlib import Path
import re

import sqlalchemy as sa
from typing_extensions import Self, TypeAlias

from . import manager
from .common import Flavour
from .db import pkg_folder
from .resolvers import CurseResolver, Defn, TukuiResolver, WowiResolver
from .utils import TocReader, bucketise, cached_property, merge_intersecting_sets, uniq

FolderAndDefnPairs: TypeAlias = 'list[tuple[list[AddonFolder], list[Defn]]]'


_SOURCE_TOC_IDS = {
    'X-Curse-Project-ID': CurseResolver.source,
    'X-Tukui-ProjectID': TukuiResolver.source,
    'X-WoWI-ID': WowiResolver.source,
}

# https://github.com/Stanzilla/WoWUIBugs/issues/68#issuecomment-830351390
_FLAVOUR_TOC_SUFFIXES = {
    Flavour.retail: [
        '_Mainline.toc',
        '-Mainline.toc',
        '.toc',
    ],
    Flavour.vanilla_classic: [
        '_Vanilla.toc',
        '-Vanilla.toc',
        '_Classic.toc',
        '-Classic.toc',
        '.toc',
    ],
    Flavour.burning_crusade_classic: [
        '_TBC.toc',
        '-TBC.toc',
        '_BCC.toc',
        '-BCC.toc',
        '.toc',
    ],
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
        elif not isinstance(other, str):
            return NotImplemented
        return self.name < other

    @classmethod
    def from_addon_path(cls, flavour: Flavour, path: Path) -> Self | None:
        for suffix in _FLAVOUR_TOC_SUFFIXES[flavour]:
            try:
                toc_reader = TocReader.from_addon_path(path, suffix)
                return cls(path.name, toc_reader)
            except FileNotFoundError:
                pass

    @cached_property
    def defns_from_toc(self) -> frozenset[Defn]:
        return frozenset(
            Defn(s, i)
            for s, i in ((s, self.toc_reader[k]) for k, s in _SOURCE_TOC_IDS.items())
            if i
        )

    @cached_property
    def version(self) -> str:
        return self.toc_reader['Version', 'X-Packaged-Version', 'X-Curse-Packaged-Version'] or ''


def _get_unreconciled_folders(manager: manager.Manager):
    pkg_folders = manager.database.execute(sa.select(pkg_folder.c.name)).scalars().all()
    unreconciled_folder_paths = (
        p
        for p in manager.config.addon_dir.iterdir()
        if p.name not in pkg_folders and p.is_dir() and not p.is_symlink()
    )
    for path in unreconciled_folder_paths:
        addon_folder = AddonFolder.from_addon_path(manager.config.game_flavour, path)
        if addon_folder:
            yield addon_folder


def get_unreconciled_folders(manager: manager.Manager) -> frozenset[AddonFolder]:
    return frozenset(_get_unreconciled_folders(manager))


async def match_toc_source_ids(
    manager: manager.Manager, leftovers: frozenset[AddonFolder]
) -> FolderAndDefnPairs:
    addons_with_toc_source_ids = [a for a in sorted(leftovers) if a.defns_from_toc]
    merged_defns = list(
        merge_intersecting_sets(a.defns_from_toc for a in addons_with_toc_source_ids)
    )
    folders_grouped_by_overlapping_defns = bucketise(
        addons_with_toc_source_ids, lambda a: next(d for d in merged_defns if a.defns_from_toc & d)
    )
    source_sort_order = list(manager.resolvers.keys())
    return [
        (f, sorted(b, key=lambda d: source_sort_order.index(d.source)))
        for b, f in folders_grouped_by_overlapping_defns.items()
    ]


async def match_folder_name_subsets(
    manager: manager.Manager, leftovers: frozenset[AddonFolder]
) -> FolderAndDefnPairs:
    catalogue = await manager.synchronise()

    matches = [
        (frozenset(e for e in leftovers if e.name in f), Defn(i.source, i.id))
        for i in catalogue.entries
        if manager.config.game_flavour in i.game_flavours
        for f in i.folders
        if f <= leftovers
    ]
    merged_folders = list(merge_intersecting_sets(f for f, _ in matches))
    matches_grouped_by_overlapping_folder_names = bucketise(
        matches, lambda v: next(f for f in merged_folders if v[0] & f)
    )

    source_sort_order = list(manager.resolvers.keys())

    def sort_key(folders: frozenset[AddonFolder], defn: Defn):
        return (-len(folders), source_sort_order.index(defn.source))

    return [
        (sorted(f), uniq(d for _, d in sorted(b, key=lambda v: sort_key(*v))))
        for f, b in matches_grouped_by_overlapping_folder_names.items()
    ]


async def match_addon_names_with_folder_names(
    manager: manager.Manager, leftovers: frozenset[AddonFolder]
) -> FolderAndDefnPairs:
    def normalise(value: str):
        return re.sub(r'[^0-9A-Za-z]', '', value.casefold())

    catalogue = await manager.synchronise()

    addon_names_to_catalogue_entries = bucketise(
        catalogue.entries, key=lambda i: normalise(i.name)
    )
    matches = (
        (a, addon_names_to_catalogue_entries.get(normalise(a.name))) for a in sorted(leftovers)
    )
    return [([a], uniq(Defn(i.source, i.id) for i in m)) for a, m in matches if m]
