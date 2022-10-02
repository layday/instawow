from __future__ import annotations

from collections.abc import Awaitable
from functools import total_ordering
from itertools import chain, product
from pathlib import Path
import re

from attrs import field, frozen
import sqlalchemy as sa
from typing_extensions import Protocol, Self

from . import manager
from ._sources.cfcore import CfCoreResolver
from ._sources.tukui import TukuiResolver
from ._sources.wowi import WowiResolver
from .common import Flavour
from .db import pkg_folder
from .resolvers import Defn
from .utils import (
    TocReader,
    as_decorated_type,
    bucketise,
    cached_property,
    gather,
    merge_intersecting_sets,
    uniq,
)


class Matcher(Protocol):
    def __call__(
        self, manager: manager.Manager, leftovers: frozenset[AddonFolder]
    ) -> Awaitable[list[tuple[list[AddonFolder], list[Defn]]]]:
        ...


_SOURCE_TOC_IDS = {
    'X-Curse-Project-ID': CfCoreResolver.metadata.id,
    'X-Tukui-ProjectID': TukuiResolver.metadata.id,
    'X-WoWI-ID': WowiResolver.metadata.id,
}

# https://github.com/Stanzilla/WoWUIBugs/issues/68#issuecomment-830351390
FLAVOUR_TOC_IDS = {
    Flavour.retail: ('Mainline',),
    Flavour.vanilla_classic: (
        'Vanilla',
        'Classic',
    ),
    Flavour.classic: (
        'Wrath',
        'WOTLKC',
    ),
}

FLAVOUR_TOC_SUFFIXES = {
    k: tuple(f'{s}{f}.toc' for s, f in product('-_', v)) for k, v in FLAVOUR_TOC_IDS.items()
}

NORMALISED_FLAVOUR_TOC_SUFFIXES = {
    k: tuple(i.lower() for i in v) for k, v in FLAVOUR_TOC_SUFFIXES.items()
}


@total_ordering
@frozen(order=False, slots=False)
class AddonFolder:
    path: Path = field(eq=False)
    toc_reader: TocReader = field(eq=False)
    name: str = field(init=False)

    def __attrs_post_init__(self) -> None:
        object.__setattr__(self, 'name', self.path.name)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            return NotImplemented
        return self.name < other.name

    @classmethod
    def from_addon_path(cls, flavour: Flavour, path: Path) -> Self | None:
        for suffix in chain(FLAVOUR_TOC_SUFFIXES[flavour], ('.toc',)):
            try:
                toc_reader = TocReader.from_addon_path(path, suffix)
                return cls(path, toc_reader)
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


@as_decorated_type(Matcher)
async def match_toc_source_ids(manager: manager.Manager, leftovers: frozenset[AddonFolder]):
    addons_with_toc_source_ids = [a for a in sorted(leftovers) if a.defns_from_toc]
    merged_defns = list(
        merge_intersecting_sets(a.defns_from_toc for a in addons_with_toc_source_ids)
    )
    folders_grouped_by_overlapping_defns = bucketise(
        addons_with_toc_source_ids, lambda a: next(d for d in merged_defns if a.defns_from_toc & d)
    )

    return [
        (
            f,
            sorted(b, key=lambda d: manager.resolvers.priority_dict[d.source]),
        )
        for b, f in folders_grouped_by_overlapping_defns.items()
    ]


@as_decorated_type(Matcher)
async def match_folder_name_subsets(manager: manager.Manager, leftovers: frozenset[AddonFolder]):
    catalogue = await manager.synchronise()

    leftovers_by_name = {l.name: l for l in leftovers}

    matches = [
        (frozenset(leftovers_by_name[n] for n in m), Defn(i.source, i.id))
        for i in catalogue.entries
        if manager.config.game_flavour in i.game_flavours
        for f in i.folders
        for m in (f & leftovers_by_name.keys(),)
        if m
    ]
    merged_folders = list(merge_intersecting_sets(f for f, _ in matches))
    matches_grouped_by_overlapping_folder_names = bucketise(
        matches, lambda v: next(f for f in merged_folders if v[0] & f)
    )

    def sort_key(folders: frozenset[AddonFolder], defn: Defn):
        return (-len(folders), manager.resolvers.priority_dict[defn.source])

    return [
        (sorted(f), uniq(d for _, d in sorted(b, key=lambda v: sort_key(*v))))
        for f, b in matches_grouped_by_overlapping_folder_names.items()
    ]


@as_decorated_type(Matcher)
async def match_addon_names_with_folder_names(
    manager: manager.Manager, leftovers: frozenset[AddonFolder]
):
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
