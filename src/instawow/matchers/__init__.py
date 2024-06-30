from __future__ import annotations

import re
from collections.abc import Awaitable, Iterable, Mapping
from itertools import chain, product
from pathlib import Path
from typing import Protocol

import attrs
from typing_extensions import Self

from .. import shared_ctx
from .._utils.compat import fauxfrozen
from .._utils.iteration import bucketise, merge_intersecting_sets, uniq
from ..catalogue import synchronise as synchronise_catalogue
from ..definitions import Defn
from ..wow_installations import Flavour
from .addon_toc import TocReader


class Matcher(Protocol):  # pragma: no cover
    def __call__(
        self, config_ctx: shared_ctx.ConfigBoundCtx, leftovers: frozenset[AddonFolder]
    ) -> Awaitable[list[tuple[list[AddonFolder], list[Defn]]]]: ...


# https://github.com/Stanzilla/WoWUIBugs/issues/68#issuecomment-830351390
# https://warcraft.wiki.gg/wiki/TOC_format#Multiple_client_flavors
FLAVOUR_TOC_IDS = {
    Flavour.Retail: ('Mainline',),
    Flavour.VanillaClassic: ('Vanilla', 'Classic'),
    Flavour.Classic: ('Cata', 'Classic'),
    Flavour.WrathClassic: ('Wrath', 'WOTLKC', 'Classic'),
}

FLAVOUR_TOC_SUFFIXES = {
    k: tuple(f'{s}{f}.toc' for s, f in product('-_', v)) for k, v in FLAVOUR_TOC_IDS.items()
}
NORMALISED_FLAVOUR_TOC_SUFFIXES = {
    k: tuple(i.lower() for i in v) for k, v in FLAVOUR_TOC_SUFFIXES.items()
}


@fauxfrozen(order=True)
class AddonFolder:
    path: Path = attrs.field(eq=False, order=False)
    toc_reader: TocReader = attrs.field(eq=False, order=False)
    name: str = attrs.field(init=False)

    def __attrs_post_init__(self) -> None:
        object.__setattr__(self, 'name', self.path.name)

    @classmethod
    def from_path(cls, flavour: Flavour, path: Path) -> Self | None:
        for suffix in chain(FLAVOUR_TOC_SUFFIXES[flavour], ('.toc',)):
            try:
                toc_reader = TocReader.from_path(path / (path.name + suffix))
                return cls(path, toc_reader)
            except FileNotFoundError:
                pass

    def get_defns_from_toc_keys(self, keys_and_ids: Iterable[tuple[str, str]]) -> frozenset[Defn]:
        return frozenset(
            Defn(s, i) for k, s in keys_and_ids for i in (self.toc_reader.get(k),) if i
        )


def _get_unreconciled_folders(config_ctx: shared_ctx.ConfigBoundCtx):
    with config_ctx.database.connect() as connection:
        pkg_folders = [n for (n,) in connection.execute('SELECT name FROM pkg_folder').fetchall()]

    unreconciled_folder_paths = (
        p
        for p in config_ctx.config.addon_dir.iterdir()
        if p.name not in pkg_folders and p.is_dir() and not p.is_symlink()
    )
    for path in unreconciled_folder_paths:
        addon_folder = AddonFolder.from_path(config_ctx.config.game_flavour, path)
        if addon_folder:
            yield addon_folder


def get_unreconciled_folders(config_ctx: shared_ctx.ConfigBoundCtx) -> frozenset[AddonFolder]:
    return frozenset(_get_unreconciled_folders(config_ctx))


async def match_toc_source_ids(
    config_ctx: shared_ctx.ConfigBoundCtx, leftovers: frozenset[AddonFolder]
):
    catalogue = await synchronise_catalogue()

    def get_catalogue_defns(extracted_defns: Iterable[Defn]):
        for defn in extracted_defns:
            entry = catalogue.keyed_entries.get((defn.source, defn.alias))
            if entry:
                for addon_key in entry.same_as:
                    if addon_key.source in config_ctx.resolvers:
                        yield Defn(addon_key.source, addon_key.id)

    def get_addon_and_defn_pairs():
        for addon in sorted(leftovers):
            defns = addon.get_defns_from_toc_keys(config_ctx.resolvers.addon_toc_key_and_id_pairs)
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
            sorted(b, key=lambda d: config_ctx.resolvers.priority_dict[d.source]),
        )
        for b, f in folders_grouped_by_overlapping_defns.items()
    ]


async def match_folder_name_subsets(
    config_ctx: shared_ctx.ConfigBoundCtx, leftovers: frozenset[AddonFolder]
):
    catalogue = await synchronise_catalogue()

    leftovers_by_name = {e.name: e for e in leftovers}

    matches = [
        (frozenset(leftovers_by_name[n] for n in m), Defn(i.source, i.id))
        for i in catalogue.entries
        if config_ctx.config.game_flavour in i.game_flavours
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
        return (-len(folders), config_ctx.resolvers.priority_dict[defn.source])

    return [
        (sorted(f), uniq(d for _, d in sorted(b, key=lambda v: sort_key(*v))))
        for f, b in matches_grouped_by_overlapping_folder_names.items()
    ]


async def match_addon_names_with_folder_names(
    config_ctx: shared_ctx.ConfigBoundCtx, leftovers: frozenset[AddonFolder]
):
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
    'toc_source_ids': match_toc_source_ids,
    'folder_name_subsets': match_folder_name_subsets,
    'addon_names_with_folder_names': match_addon_names_with_folder_names,
}
