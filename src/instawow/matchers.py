from __future__ import annotations

import re
from collections.abc import Awaitable, Iterable, Mapping
from functools import cached_property
from itertools import chain, product
from pathlib import Path
from typing import Protocol, TypeVar

import sqlalchemy as sa
from attrs import field, frozen
from typing_extensions import Self

from . import manager
from ._addon_hashing import generate_wowup_addon_hash
from .common import AddonHashMethod, Defn, Flavour
from .db import pkg_folder
from .utils import (
    TocReader,
    assert_decorated_type,
    bucketise,
    gather,
    merge_intersecting_sets,
    uniq,
)


class Matcher(Protocol):
    def __call__(
        self, manager: manager.Manager, leftovers: frozenset[AddonFolder]
    ) -> Awaitable[list[tuple[list[AddonFolder], list[Defn]]]]:
        ...


_TMatcher = TypeVar('_TMatcher', bound=Matcher)


class assert_matcher(assert_decorated_type[_TMatcher]):
    pass


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


@frozen(order=True, slots=False)
class AddonFolder:
    path: Path = field(eq=False, order=False)
    toc_reader: TocReader = field(eq=False, order=False)
    name: str = field(init=False)

    def __attrs_post_init__(self) -> None:
        object.__setattr__(self, 'name', self.path.name)

    @classmethod
    def from_addon_path(cls, flavour: Flavour, path: Path) -> Self | None:
        for suffix in chain(FLAVOUR_TOC_SUFFIXES[flavour], ('.toc',)):
            try:
                toc_reader = TocReader.from_path(path / (path.name + suffix))
                return cls(path, toc_reader)
            except FileNotFoundError:
                pass

    def hash_contents(self, __method: AddonHashMethod) -> str:
        return generate_wowup_addon_hash(self.path)

    def get_defns_from_toc_keys(self, keys_and_ids: Iterable[tuple[str, str]]) -> frozenset[Defn]:
        return frozenset(Defn(s, i) for k, s in keys_and_ids for i in (self.toc_reader[k],) if i)

    @cached_property
    def version(self) -> str:
        return self.toc_reader['Version', 'X-Packaged-Version', 'X-Curse-Packaged-Version'] or ''


def _get_unreconciled_folders(manager: manager.Manager):
    with manager.database.connect() as connection:
        pkg_folders = connection.execute(sa.select(pkg_folder.c.name)).scalars().all()

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


@assert_matcher
async def match_toc_source_ids(manager: manager.Manager, leftovers: frozenset[AddonFolder]):
    addons_with_toc_source_ids = [
        (a, d)
        for a in sorted(leftovers)
        for d in (a.get_defns_from_toc_keys(manager.resolvers.addon_toc_key_and_id_pairs),)
        if d
    ]
    merged_defns_by_constituent_defn = {
        i: s for s in merge_intersecting_sets(d for _, d in addons_with_toc_source_ids) for i in s
    }
    folders_grouped_by_overlapping_defns = bucketise(
        addons_with_toc_source_ids,
        lambda i: merged_defns_by_constituent_defn[next(iter(i[1]))],
    )
    return [
        (
            [n for n, _ in f],
            sorted(b, key=lambda d: manager.resolvers.priority_dict[d.source]),
        )
        for b, f in folders_grouped_by_overlapping_defns.items()
    ]


@assert_matcher
async def match_folder_hashes(manager: manager.Manager, leftovers: frozenset[AddonFolder]):
    matches = await gather(
        r.get_folder_hash_matches(leftovers) for r in manager.resolvers.values()
    )
    flattened_matches = [t for g in matches for t in g]
    merged_folders_by_constituent_folder = {
        i: s for s in merge_intersecting_sets(f for _, f in flattened_matches) for i in s
    }
    matches_grouped_by_overlapping_folder_names = bucketise(
        flattened_matches, lambda v: merged_folders_by_constituent_folder[next(iter(v[1]))]
    )
    return sorted(
        (
            sorted(f),
            sorted(uniq(d for d, _ in b), key=lambda d: manager.resolvers.priority_dict[d.source]),
        )
        for f, b in matches_grouped_by_overlapping_folder_names.items()
    )


@assert_matcher
async def match_folder_name_subsets(manager: manager.Manager, leftovers: frozenset[AddonFolder]):
    catalogue = await manager.synchronise()

    leftovers_by_name = {e.name: e for e in leftovers}

    matches = [
        (frozenset(leftovers_by_name[n] for n in m), Defn(i.source, i.id))
        for i in catalogue.entries
        if manager.config.game_flavour in i.game_flavours
        for f in i.folders
        for m in (f & leftovers_by_name.keys(),)
        if m
    ]
    merged_folders_by_constituent_folder = {
        i: s for s in merge_intersecting_sets(f for f, _ in matches) for i in s
    }
    matches_grouped_by_overlapping_folder_names = bucketise(
        matches, lambda v: merged_folders_by_constituent_folder[next(iter(v[0]))]
    )

    def sort_key(folders: frozenset[AddonFolder], defn: Defn):
        return (-len(folders), manager.resolvers.priority_dict[defn.source])

    return [
        (sorted(f), uniq(d for _, d in sorted(b, key=lambda v: sort_key(*v))))
        for f, b in matches_grouped_by_overlapping_folder_names.items()
    ]


@assert_matcher
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


# In order of increasing heuristicitivenessitude
DEFAULT_MATCHERS: Mapping[str, Matcher] = {
    'toc_source_ids': match_toc_source_ids,
    'folder_name_subsets': match_folder_name_subsets,
    'folder_hashes': match_folder_hashes,
    'addon_names_with_folder_names': match_addon_names_with_folder_names,
}
