from __future__ import annotations

from functools import total_ordering
from typing import TYPE_CHECKING, FrozenSet, Iterable, List, Tuple

from loguru import logger

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


@total_ordering
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

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (self.__class__, str)):
            return NotImplemented
        return self.name == other

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, (self.__class__, str)):
            return NotImplemented
        return self.name < other        # type: ignore


def get_folders(manager: Manager, exclude_own: bool = True) -> FrozenSet[AddonFolder]:
    def make_addon_folder(path):
        try:
            return (path.name not in own_folders
                    and AddonFolder(path.name, TocReader.from_path_name(path)))
        except (FileNotFoundError, NotADirectoryError):
            logger.info(f'skipping {path}')

    if exclude_own:
        own_folders = {f.name for f in manager.db_session.query(PkgFolder).all()}
    else:
        own_folders = set()
    return frozenset(filter(None, map(make_addon_folder, manager.config.addon_dir.iterdir())))


async def match_toc_ids(manager: Manager, leftovers: FrozenSet[AddonFolder]) -> _Groups:
    "Attempt to match add-ons from source IDs contained in TOC files."
    def keyer(value):
        return next(d for d in defns if value.defns_from_toc & d)

    matches = [a for a in sorted(leftovers) if a.defns_from_toc]
    defns = list(merge_intersecting_sets(a.defns_from_toc for a in matches))
    results = await manager.resolve(list(frozenset.union(*defns, frozenset())))      # type: ignore
    return [(f, [results[d] for d in b]) for b, f in bucketise(matches, keyer).items()]


async def match_dir_names(manager: Manager, leftovers: FrozenSet[AddonFolder]) -> _Groups:
    "Attempt to match folders against the CurseForge and WoWInterface catalogues."
    async def fetch_combined_folders():
        url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
               'combined-folders.compact.json')   # v1
        async with manager.web_client.get(url) as response:
            return await response.json(content_type=None)

    def keyer(value):
        return next(f for f in folders if value[0] & f)

    # We can't use an intersection here because it's not guaranteed to return ``AddonFolder``s
    matches = [(frozenset(filter(f.__contains__, leftovers)), Defn(*d))
               for d, c, f in await fetch_combined_folders()
               if manager.config.game_flavour in c
               and frozenset(f) <= leftovers]
    folders = list(merge_intersecting_sets(f for f, _ in matches))
    results = await manager.resolve(list({d for _, d in matches}))
    return [(sorted(f), [results[d] for _, d in b]) for f, b in bucketise(matches, keyer).items()]
