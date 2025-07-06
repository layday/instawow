from __future__ import annotations

import os
import re
from collections.abc import Awaitable, Iterable, Mapping
from itertools import chain, product
from pathlib import Path
from typing import Protocol, Self

import attrs

from .. import config_ctx
from .._utils.attrs import fauxfrozen
from .._utils.iteration import bucketise, merge_intersecting_sets, uniq
from ..catalogue import synchronise as synchronise_catalogue
from ..definitions import Defn
from ..wow_installations import Flavour, FlavourTocSuffixes, to_flavour
from .addon_toc import TocReader


class Matcher(Protocol):  # pragma: no cover
    def __call__(
        self, leftovers: frozenset[AddonFolder]
    ) -> Awaitable[list[tuple[list[AddonFolder], list[Defn]]]]: ...


_FLAVOUR_TOC_EXTENSIONS = {
    to_flavour(s): tuple(f'{s}{f}.toc' for s, f in product('-_', s.value))
    for s in FlavourTocSuffixes
}
NORMALISED_FLAVOUR_TOC_EXTENSIONS = {
    k: tuple(i.lower() for i in v) for k, v in _FLAVOUR_TOC_EXTENSIONS.items()
}


@fauxfrozen(order=True)
class AddonFolder:
    path: Path = attrs.field(eq=False, order=False)
    toc_reader: TocReader = attrs.field(eq=False, order=False)
    name: str = attrs.field(init=False)

    def __attrs_post_init__(self) -> None:
        object.__setattr__(self, 'name', self.path.name)

    @classmethod
    def from_path(cls, flavour: Flavour, parent_path: Path) -> Self | None:
        suffixes = tuple(chain(NORMALISED_FLAVOUR_TOC_EXTENSIONS[flavour], ('.toc',)))

        with os.scandir(parent_path) as iter_parent_dir:
            match = next(
                (c for c in iter_parent_dir if c.name.lower().endswith(suffixes)),
                None,
            )

        if match is not None:
            toc_reader = TocReader.from_path(Path(match))
            return cls(parent_path, toc_reader)

    def get_defns_from_toc_keys(self, keys_and_ids: Iterable[tuple[str, str]]) -> frozenset[Defn]:
        return frozenset(
            Defn(s, i) for k, s in keys_and_ids for i in (self.toc_reader.get(k),) if i
        )


def _get_unreconciled_folders():
    config = config_ctx.config()
    flavour = to_flavour(config.track)

    with config_ctx.database() as connection:
        pkg_folders = [n for (n,) in connection.execute('SELECT name FROM pkg_folder').fetchall()]

    unreconciled_folder_paths = (
        p
        for p in config.addon_dir.iterdir()
        if p.name not in pkg_folders and p.is_dir() and not p.is_symlink()
    )
    for path in unreconciled_folder_paths:
        addon_folder = AddonFolder.from_path(flavour, path)
        if addon_folder:
            yield addon_folder


def get_unreconciled_folders() -> frozenset[AddonFolder]:
    return frozenset(_get_unreconciled_folders())


async def _match_toc_source_ids(leftovers: frozenset[AddonFolder]):
    resolvers = config_ctx.resolvers()
    catalogue = await synchronise_catalogue()

    def get_catalogue_defns(extracted_defns: Iterable[Defn]):
        for defn in extracted_defns:
            entry = catalogue.keyed_entries.get((defn.source, defn.alias))
            if entry:
                for addon_key in entry.same_as:
                    if addon_key.source in resolvers:
                        yield Defn(addon_key.source, addon_key.id)

    def get_addon_and_defn_pairs():
        for addon in sorted(leftovers):
            defns = addon.get_defns_from_toc_keys(resolvers.addon_toc_key_and_id_pairs)
            if defns:
                yield (addon, defns | frozenset(get_catalogue_defns(defns)))

    matches = list(get_addon_and_defn_pairs())
    merged_defns_by_constituent_defn = {
        i: s for s in merge_intersecting_sets(d for _, d in matches) for i in s
    }
    folders_grouped_by_overlapping_defns = bucketise(
        matches,
        lambda i: merged_defns_by_constituent_defn[next(iter(i[1]))],
    )
    return [
        (
            [n for n, _ in f],
            sorted(b, key=lambda d: resolvers.priority_dict[d.source]),
        )
        for b, f in folders_grouped_by_overlapping_defns.items()
    ]


async def _match_folder_name_subsets(leftovers: frozenset[AddonFolder]):
    flavour = to_flavour(config_ctx.config().track)
    resolvers = config_ctx.resolvers()
    catalogue = await synchronise_catalogue()

    leftovers_by_name = {e.name: e for e in leftovers}

    matches = [
        (frozenset(leftovers_by_name[n] for n in m), Defn(i.source, i.id))
        for i in catalogue.entries
        if flavour in i.game_flavours
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
        return (-len(folders), resolvers.priority_dict[defn.source])

    return [
        (sorted(f), uniq(d for _, d in sorted(b, key=lambda v: sort_key(*v))))
        for f, b in matches_grouped_by_overlapping_folder_names.items()
    ]


async def _match_addon_names_with_folder_names(leftovers: frozenset[AddonFolder]):
    def normalise(value: str):
        return re.sub(r'[^0-9A-Za-z]', '', value.casefold())

    catalogue = await synchronise_catalogue()

    addon_names_to_catalogue_entries = bucketise(
        catalogue.entries, key=lambda i: normalise(i.name)
    )
    matches = (
        (a, addon_names_to_catalogue_entries.get(normalise(a.name))) for a in sorted(leftovers)
    )
    return [([a], uniq(Defn(i.source, i.id) for i in m)) for a, m in matches if m]


# In order of increasing heuristicitivenessitude
DEFAULT_MATCHERS: Mapping[str, Matcher] = {
    'toc_source_ids': _match_toc_source_ids,
    'folder_name_subsets': _match_folder_name_subsets,
    'addon_names_with_folder_names': _match_addon_names_with_folder_names,
}
