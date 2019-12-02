from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, List, Set, Tuple
from typing import NamedTuple

from .models import PkgFolder
from .resolvers import Defn
from .utils import TocReader, run_in_thread as t

if TYPE_CHECKING:
    from .manager import Manager


_TocReader = t(TocReader.from_path_name)


class _Addon(NamedTuple):

    name: str
    reader: TocReader

    @property
    def version(self) -> str:
        return self.reader['Version', 'X-Packaged-Version', 'X-Curse-Packaged-Version'].value


async def match_toc_ids(manager: Manager, leftovers: Set[str]) -> Iterable[Tuple[List[_Addon], List[Any]]]:
    "Attempt to match add-ons from host IDs contained in TOC files."
    ids_to_sources = {'X-Curse-Project-ID': 'curse',
                      'X-Tukui-ProjectID': 'tukui',
                      'X-WoWI-ID': 'wowi',}

    def merge_ids_and_dirs(matches, *, buckets=[]):
        try:
            match = next(matches)
        except StopIteration:
            return buckets
        else:
            dirs, ids = match
            for index, (ex_dirs, ex_ids) in enumerate(buckets):
                if ex_ids & ids:
                    buckets[index] = (ex_dirs + dirs, ex_ids | ids)
                    break
            else:
                buckets.append(match)
            return merge_ids_and_dirs(matches)

    dir_tocs = [(n, await _TocReader(manager.config.addon_dir / n))
                for n in sorted(leftovers)]
    maybe_ids = (((n, r), (r[i] for i in ids_to_sources)) for n, r in dir_tocs)
    buckets = merge_ids_and_dirs(([t], {Defn(ids_to_sources[v.key], v.value) for v in i if v})
                                 for t, i in maybe_ids)
    results = await manager.resolve(list({u for _, i in buckets for u in i}))
    groups = (([_Addon(*i) for i in k], [results[i] for i in v])
              for k, v in buckets)
    return groups


async def match_dir_names(manager: Manager, leftovers: Set[str]) -> Iterable[Tuple[List[_Addon], List[Any]]]:
    "Attempt to match folders against the CurseForge and WoWInterface catalogue."
    async def fetch_combined_folders():
        url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
               'combined-folders.compact.json')   # v1
        async with manager.web_client.get(url) as response:
            return await response.json(content_type='text/plain')

    def merge_dirs_and_ids(matches, *, buckets=[]):
        try:
            match = next(matches)
        except StopIteration:
            return buckets
        else:
            dirs, id_ = match
            for index, (ex_dirs, ex_ids) in enumerate(buckets):
                if ex_dirs & dirs:
                    buckets[index] = (ex_dirs | dirs, ex_ids | {id_})
                    break
            else:
                buckets.append((dirs, {id_}))
            return merge_dirs_and_ids(matches)

    async def make_toc(dirs):
        return [_Addon(d, await _TocReader(manager.config.addon_dir / d))
                for d in sorted(dirs)]

    combined_folders = await fetch_combined_folders()
    dirs = ((set(f), Defn(*d)) for d, c, f in combined_folders
            if manager.config.game_flavour in c)
    buckets = merge_dirs_and_ids((d & leftovers, u) for d, u in dirs
                                 if d & leftovers)
    results = await manager.resolve(list({u for _, i in buckets for u in i}))
    dir_tocs = [await make_toc(d) for d, _ in buckets]
    groups = ((d, [results[i] for i in v])
              for d, (_, v) in zip(dir_tocs, buckets))
    return groups


def get_leftovers(manager: Manager) -> Set[str]:
    addons = {f.name for f in manager.config.addon_dir.iterdir() if f.is_dir()}
    leftovers = addons - {f.name for f in manager.db_session.query(PkgFolder).all()}
    return leftovers
