from __future__ import annotations

from typing import TYPE_CHECKING, FrozenSet, Iterable, List, Tuple

from .models import PkgFolder
from .resolvers import Defn
from .utils import (TocReader, bucketise, cached_property, merge_intersecting_sets,
                    run_in_thread as t)

if TYPE_CHECKING:
    from .exceptions import ManagerResult
    from .manager import Manager

    _Groups = Iterable[Tuple[List[AddonFolder], List[ManagerResult]]]


_ids_to_sources = {'X-Curse-Project-ID': 'curse',
                   'X-Tukui-ProjectID': 'tukui',
                   'X-WoWI-ID': 'wowi',}

_make_reader = t(TocReader.from_path_name)


class AddonFolder:
    def __init__(self, name: str, toc_reader: TocReader) -> None:
        self.name = name
        self.toc_reader = toc_reader

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__}: {self.name}>'

    @cached_property
    def defns_from_toc(self) -> FrozenSet[Defn]:
        return frozenset(Defn(s, i) for s, i in
                         ((s, self.toc_reader[k].value) for k, s in _ids_to_sources.items())
                         if i)

    @cached_property
    def version(self) -> str:
        return self.toc_reader['Version',
                              'X-Packaged-Version',
                              'X-Curse-Packaged-Version'].value


def get_leftovers(manager: Manager) -> FrozenSet[str]:
    addons = {f.name for f in manager.config.addon_dir.iterdir() if f.is_dir()}
    leftovers = addons - {f.name for f in manager.db_session.query(PkgFolder).all()}
    return frozenset(leftovers)


async def wrap_addons(manager: Manager, folders: FrozenSet[str]) -> List[AddonFolder]:
    return [AddonFolder(f, await _make_reader(manager.config.addon_dir / f))
            for f in sorted(folders)]


async def match_toc_ids(manager: Manager, leftovers: FrozenSet[str]) -> _Groups:
    "Attempt to match add-ons from source IDs contained in TOC files."
    def keyer(value):
        return next(d for d in defns if value.defns_from_toc & d)

    matches = [a for a in await wrap_addons(manager, leftovers) if a.defns_from_toc]
    defns = list(merge_intersecting_sets(a.defns_from_toc for a in matches))
    results = await manager.resolve(list(frozenset.union(*defns, frozenset())))      # type: ignore
    return [(f, [results[d] for d in sorted(b)])
            for b, f in bucketise(matches, keyer).items()]


async def match_dir_names(manager: Manager, leftovers: FrozenSet[str]) -> _Groups:
    "Attempt to match folders against the CurseForge and WoWInterface catalogues."
    async def fetch_combined_folders():
        url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
               'combined-folders.compact.json')   # v1
        async with manager.web_client.get(url) as response:
            return await response.json(content_type=None)

    def keyer(value):
        return next(f for f in folders if value[0] & f)

    matches = [(frozenset(f) & leftovers, Defn(*d))
               for d, c, f in await fetch_combined_folders()
               if manager.config.game_flavour in c
               and frozenset(f) <= leftovers]
    folders = list(merge_intersecting_sets(f for f, _ in matches))
    results = await manager.resolve(list({d for _, d in matches}))
    return [(await wrap_addons(manager, f),
             [results[d] for _, d in sorted(b)]) for f, b in bucketise(matches, keyer).items()]
