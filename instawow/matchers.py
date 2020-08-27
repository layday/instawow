from __future__ import annotations

from contextlib import suppress
from functools import total_ordering
from pathlib import Path
import re
from typing import TYPE_CHECKING, FrozenSet, List, Tuple, cast

from .models import PkgFolder
from .resolvers import CurseResolver, Defn, TukuiResolver, WowiResolver
from .utils import TocReader, bucketise, cached_property, merge_intersecting_sets, uniq

if TYPE_CHECKING:
    from .manager import Manager

    MatchGroups = List[Tuple[List['AddonFolder'], List[Defn]]]


_ids_to_sources = {
    'X-Curse-Project-ID': CurseResolver.source,
    'X-Tukui-ProjectID': TukuiResolver.source,
    'X-WoWI-ID': WowiResolver.source,
}
_sources_to_sort_weights = {
    CurseResolver.source: 0,
    TukuiResolver.source: 2,
    WowiResolver.source: 1,
}


@total_ordering
class AddonFolder:
    def __init__(self, name: str, toc_reader: TocReader) -> None:
        self.name = name
        self.toc_reader = toc_reader

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}: {self.name}>'

    @cached_property
    def defns_from_toc(self) -> FrozenSet[Defn]:
        return frozenset(
            Defn(source=s, name=i)
            for s, i in ((s, self.toc_reader[k].value) for k, s in _ids_to_sources.items())
            if i
        )

    @cached_property
    def version(self) -> str:
        return self.toc_reader['Version', 'X-Packaged-Version', 'X-Curse-Packaged-Version'].value

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (self.__class__, str)):
            return NotImplemented
        return self.name == other

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, (self.__class__, str)):
            return NotImplemented
        return self.name < other


def get_folders(manager: Manager, exclude_own: bool = True) -> FrozenSet[AddonFolder]:
    def make_addon_folder(path: Path):
        if path.name not in own_folders and path.is_dir() and not path.is_symlink():
            with suppress(FileNotFoundError):
                return AddonFolder(path.name, TocReader.from_parent_folder(path))

    if exclude_own:
        own_folders = {f.name for f in manager.database.query(PkgFolder).all()}
    else:
        own_folders = set()
    return frozenset(f for f in map(make_addon_folder, manager.config.addon_dir.iterdir()) if f)


async def match_toc_ids(manager: Manager, leftovers: FrozenSet[AddonFolder]) -> MatchGroups:
    "Attempt to match add-ons from TOC-file source ID entries."

    def bucket_keyer(value: AddonFolder):
        return next(d for d in defns if value.defns_from_toc & d)

    def sort_keyer(value: Defn):
        return _sources_to_sort_weights[value.source]

    matches = [a for a in sorted(leftovers) if a.defns_from_toc]
    defns = list(merge_intersecting_sets(a.defns_from_toc for a in matches))
    return [(f, sorted(b, key=sort_keyer)) for b, f in bucketise(matches, bucket_keyer).items()]


async def match_dir_names(manager: Manager, leftovers: FrozenSet[AddonFolder]) -> MatchGroups:
    "Attempt to match folders against the master catalogue."

    def bucket_keyer(value: Tuple[FrozenSet[AddonFolder], Defn]):
        return next(f for f in folders if value[0] & f)

    def sort_keyer(value: Tuple[FrozenSet[AddonFolder], Defn]):
        folders, defn = value
        return (-len(folders), _sources_to_sort_weights[defn.source])

    await manager.synchronise()

    # We can't use an intersection here because it's not guaranteed to
    # return ``AddonFolder``s - the duck typing semantics of '&' appear
    # to be undefined
    matches = [
        (
            frozenset(e for e in leftovers if e in cast('List[AddonFolder]', f)),
            Defn(source=i.source, name=i.id),
        )
        for i in manager.catalogue.__root__
        for f in i.folders
        if manager.config.game_flavour in i.compatibility and frozenset(f) <= leftovers
    ]
    folders = list(merge_intersecting_sets(f for f, _ in matches))
    return [
        (sorted(f), uniq(d for _, d in sorted(b, key=sort_keyer)))
        for f, b in bucketise(matches, bucket_keyer).items()
    ]


async def match_toc_names(manager: Manager, leftovers: FrozenSet[AddonFolder]) -> MatchGroups:
    "Attempt to match add-ons from TOC-file name entries."

    def normalise(value: str):
        return re.sub(r'[^0-9A-Za-z]', '', value.casefold())

    await manager.synchronise()

    norm_to_items = bucketise(manager.catalogue.__root__, key=lambda i: normalise(i.name))
    matches = ((e, norm_to_items.get(normalise(e.name))) for e in sorted(leftovers))
    return [([e], uniq(Defn(source=i.source, name=i.id) for i in m)) for e, m in matches if m]
