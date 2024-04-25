from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from itertools import product, tee, zip_longest
from typing import Any, Literal

import iso8601
from typing_extensions import Never, TypedDict
from typing_extensions import NotRequired as N
from yarl import URL

from .. import results as R
from .._logging import logger
from .._utils.aio import cancel_tasks
from .._utils.compat import StrEnum
from .._utils.iteration import batched
from .._utils.web import as_plain_text_data_url, extract_byte_range_offset
from ..catalogue.cataloguer import AddonKey, CatalogueEntry
from ..definitions import ChangelogFormat, Defn, SourceMetadata, Strategy
from ..http import CACHE_INDEFINITELY, ClientSessionType
from ..matchers.addon_toc import TocReader
from ..pkg_archives import find_archive_addon_tocs
from ..resolvers import BaseResolver, HeadersIntent, PkgCandidate
from ..wow_installations import Flavour, FlavourVersionRange


# Not exhaustive (as you might've guessed).  Reference:
# https://docs.github.com/en/rest/reference/repos
class _GithubRepo(TypedDict):
    id: int  # Unique, stable repository ID
    name: str  # the repo in user-or-org/repo
    full_name: str  # user-or-org/repo
    description: str | None
    url: str
    html_url: str


class _GithubRelease(TypedDict):
    tag_name: str  # Hopefully the version
    published_at: str  # ISO datetime
    assets: list[_GithubRelease_Asset]
    body: str
    draft: bool
    prerelease: bool


class _GithubRelease_Asset(TypedDict):
    url: str
    name: str  # filename
    content_type: str  # mime type
    state: Literal['starter', 'uploaded']
    browser_download_url: Never  # Fake type to prevent misuse; actually a string


class _PackagerReleaseJson(TypedDict):
    releases: list[_PackagerReleaseJson_Release]


class _PackagerReleaseJson_Release(TypedDict):
    name: N[str]  # Added in https://github.com/BigWigsMods/packager/commit/7812bcd
    version: N[str]  # As above
    filename: str
    nolib: bool
    metadata: list[_PackagerReleaseJson_Release_Metadata]


class _PackagerReleaseJson_Release_Metadata(TypedDict):
    flavor: _PackagerReleaseJsonFlavor
    interface: int


class _PackagerReleaseJsonFlavor(StrEnum):
    Retail = 'mainline'
    VanillaClassic = 'classic'
    Classic = 'wrath'
    CataclysmClassic = 'cata'


class GithubResolver(BaseResolver):
    metadata = SourceMetadata(
        id='github',
        name='GitHub',
        strategies=frozenset(
            {
                Strategy.AnyFlavour,
                Strategy.AnyReleaseType,
                Strategy.VersionEq,
            }
        ),
        changelog_format=ChangelogFormat.Markdown,
        addon_toc_key=None,
    )
    requires_access_token = None

    __api_url = URL('https://api.github.com/')

    __generated_catalogue_csv_url = (
        'https://raw.githubusercontent.com/layday/github-wow-addon-catalogue/main/addons.csv'
    )

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    async def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str]:
        headers = dict[str, str]()

        if intent is HeadersIntent.Download:
            headers['Accept'] = 'application/octet-stream'

        access_token = self._get_access_token(self._manager_ctx.config.global_config, 'github')
        if access_token:
            headers['Authorization'] = f'token {access_token}'

        return headers

    async def __find_match_from_zip_contents(
        self,
        assets: list[_GithubRelease_Asset],
        desired_flavours: tuple[Flavour, ...] | None,
    ):
        candidates = [
            a
            for a in assets
            if a['state'] == 'uploaded'
            and a['content_type'] in {'application/zip', 'application/x-zip-compressed'}
            and a['name'].endswith('.zip')
            # TODO: Is there a better way to detect nolib?
            and '-nolib' not in a['name']
        ]
        if not candidates:
            return None

        import zipfile
        from io import BytesIO

        from aiohttp import hdrs

        from ..matchers import NORMALISED_FLAVOUR_TOC_SUFFIXES

        download_headers = await self.make_request_headers(HeadersIntent.Download)

        if desired_flavours is None:
            desired_flavours = tuple(Flavour)

        desired_version_ranges = {
            f.to_flavour_keyed_enum(FlavourVersionRange) for f in desired_flavours
        }
        desired_toc_suffixes = tuple(
            s for f in desired_flavours for s in NORMALISED_FLAVOUR_TOC_SUFFIXES[f]
        )
        all_flavourful_toc_suffixes = tuple(
            i for s in NORMALISED_FLAVOUR_TOC_SUFFIXES.values() for i in s
        )

        matching_asset = None

        for candidate in candidates:
            logger.info(f'looking for match in zip file: {candidate["browser_download_url"]}')

            addon_zip_stream = BytesIO()
            dynamic_addon_zip = None
            is_zip_complete = False

            download_url = candidate['url']

            # A large enough initial offset that we won't typically have to
            # resort to extracting the ECD.
            directory_offset = str(-25_000)

            for _ in range(2):
                logger.debug(f'fetching {directory_offset} bytes from {candidate["name"]}')

                async with self._manager_ctx.web_client.get(
                    download_url,
                    expire_after=CACHE_INDEFINITELY,
                    headers={
                        **download_headers,
                        hdrs.RANGE: f'bytes={directory_offset}',
                    },
                ) as directory_range_response:
                    if not directory_range_response.ok:
                        # File size under 25 KB.
                        if directory_range_response.status == 416:  # Range Not Satisfiable
                            async with self._manager_ctx.web_client.get(
                                download_url,
                                expire_after=CACHE_INDEFINITELY,
                                headers=download_headers,
                                raise_for_status=True,
                            ) as addon_zip_response:
                                addon_zip_stream.write(await addon_zip_response.read())

                            is_zip_complete = True
                            dynamic_addon_zip = zipfile.ZipFile(addon_zip_stream)
                            break

                        directory_range_response.raise_for_status()

                    else:
                        addon_zip_stream.seek(
                            extract_byte_range_offset(
                                directory_range_response.headers[hdrs.CONTENT_RANGE]
                            )
                        )
                        addon_zip_stream.write(await directory_range_response.read())

                        try:
                            dynamic_addon_zip = zipfile.ZipFile(addon_zip_stream)
                        except zipfile.BadZipFile:
                            zipfile_internal: Any = zipfile

                            end_rec_data = zipfile_internal._EndRecData(addon_zip_stream)
                            if end_rec_data is None:
                                break

                            directory_offset = f'{end_rec_data[zipfile_internal._ECD_OFFSET]}-'
                        else:
                            break

            if dynamic_addon_zip is None:
                logger.warning('directory marker not found')
                continue

            toc_filenames = {
                n
                for n, h in find_archive_addon_tocs(f.filename for f in dynamic_addon_zip.filelist)
                if h in candidate['name']  # Folder name is a substring of zip name.
            }
            if not toc_filenames:
                continue

            game_flavour_from_toc_filename = any(
                n.lower().endswith(desired_toc_suffixes) for n in toc_filenames
            )
            if game_flavour_from_toc_filename:
                matching_asset = candidate
                break

            try:
                main_toc_filename = min(
                    (
                        n
                        for n in toc_filenames
                        if not n.lower().endswith(all_flavourful_toc_suffixes)
                    ),
                    key=len,
                )
            except ValueError:
                continue

            if not is_zip_complete:
                a, b = tee(dynamic_addon_zip.filelist)
                next(b, None)
                main_toc_file_offset, following_file = next(
                    (f.header_offset, n)
                    for f, n in zip_longest(a, b)
                    if f.filename == main_toc_filename
                )
                # If this is the last file in the list, download to eof. In theory,
                # we could detect where the zip directory starts.
                following_file_offset = following_file.header_offset if following_file else ''

                logger.debug(f'fetching {main_toc_filename} from {candidate["name"]}')
                async with self._manager_ctx.web_client.get(
                    download_url,
                    expire_after=CACHE_INDEFINITELY,
                    headers={
                        **download_headers,
                        hdrs.RANGE: f'bytes={main_toc_file_offset}-{following_file_offset}',
                    },
                    raise_for_status=True,
                ) as toc_file_range_response:
                    addon_zip_stream.seek(main_toc_file_offset)
                    addon_zip_stream.write(await toc_file_range_response.read())

            toc_file_text = dynamic_addon_zip.read(main_toc_filename).decode('utf-8-sig')
            toc_reader = TocReader(toc_file_text)

            logger.debug(
                f'found interface versions {toc_reader.interfaces!r} in {main_toc_filename}'
            )
            if toc_reader.interfaces and any(
                r.contains(i) for r, i in product(desired_version_ranges, toc_reader.interfaces)
            ):
                matching_asset = candidate
                break

        return matching_asset

    async def __find_match_from_release_json(
        self,
        assets: list[_GithubRelease_Asset],
        release_json_asset: _GithubRelease_Asset,
        desired_flavours: tuple[Flavour, ...] | None,
    ):
        logger.info(
            f'looking for match in release.json: {release_json_asset["browser_download_url"]}'
        )

        download_headers = await self.make_request_headers(HeadersIntent.Download)

        async with self._manager_ctx.web_client.get(
            release_json_asset['url'],
            expire_after=timedelta(days=1),
            headers=download_headers,
            raise_for_status=True,
        ) as response:
            packager_metadata: _PackagerReleaseJson = await response.json(
                content_type=None  # application/octet-stream
            )

        subreleases = packager_metadata['releases']
        if not subreleases:
            return None

        if desired_flavours:
            desired_release_json_flavors = {
                f.to_flavour_keyed_enum(_PackagerReleaseJsonFlavor) for f in desired_flavours
            }
            desired_version_ranges = {
                f.to_flavour_keyed_enum(FlavourVersionRange) for f in desired_flavours
            }

            def is_compatible(release: _PackagerReleaseJson_Release):  # pyright: ignore[reportRedeclaration]
                for metadata in release['metadata']:
                    if metadata['flavor'] in desired_release_json_flavors:
                        if any(r.contains(metadata['interface']) for r in desired_version_ranges):
                            return True

                        logger.info(
                            f'flavor and interface mismatch: {metadata["interface"]} not found in '
                            f'{[r.value for r in desired_version_ranges]}'
                        )

                return False

        else:

            def is_compatible(release: _PackagerReleaseJson_Release):
                return True

        matching_release = next(
            (r for r in subreleases if not r['nolib'] and is_compatible(r)), None
        )
        if matching_release is None:
            return None

        matching_asset = next(
            (
                a
                for a in assets
                if a['name'] == matching_release['filename'] and a['state'] == 'uploaded'
            ),
            None,
        )
        return matching_asset

    async def __find_match(
        self,
        release: _GithubRelease,
        desired_flavour_groups: Sequence[tuple[Flavour, ...] | None],
    ):
        assets = release['assets']

        release_json = next(
            (a for a in assets if a['name'] == 'release.json' and a['state'] == 'uploaded'),
            None,
        )
        for desired_flavours in desired_flavour_groups:
            if release_json:
                asset = await self.__find_match_from_release_json(
                    assets, release_json, desired_flavours
                )
            else:
                asset = await self.__find_match_from_zip_contents(assets, desired_flavours)

            if asset:
                return (release, asset)

    async def _resolve_one(self, defn: Defn, metadata: None) -> PkgCandidate:
        github_headers = await self.make_request_headers()

        id_or_alias = defn.id or defn.alias
        if id_or_alias.isdigit():
            repo_url = self.__api_url / 'repositories' / id_or_alias
        else:
            repo_url = self.__api_url / 'repos' / defn.alias

        async with self._manager_ctx.web_client.get(
            repo_url, expire_after=timedelta(hours=1), headers=github_headers
        ) as response:
            if response.status == 404:
                raise R.PkgNonexistent
            response.raise_for_status()

            project: _GithubRepo = await response.json()

        if defn.strategies.version_eq:
            release_url = URL(project['url']) / 'releases/tags' / defn.strategies.version_eq
        else:
            # Includes pre-releases
            release_url = (URL(project['url']) / 'releases').with_query(
                # Default is 30 but we're more conservative
                per_page='10'
            )

        async with self._manager_ctx.web_client.get(
            release_url, expire_after=timedelta(minutes=5), headers=github_headers
        ) as response:
            if response.status == 404:
                raise R.PkgFilesMissing('no releases found')
            response.raise_for_status()

            release_json: _GithubRelease | list[_GithubRelease] = await response.json()
            if not isinstance(release_json, list):
                release_json = [release_json]

        # Only users with push access will get draft releases
        # but let's filter them out just in case.
        releases = (r for r in release_json if r['draft'] is False)

        if not defn.strategies.any_release_type:
            releases = (r for r in releases if r['prerelease'] is False)

        first_release = next(releases, None)
        if first_release is None:
            raise R.PkgFilesNotMatching(defn.strategies)

        desired_flavour_groups = self._manager_ctx.config.game_flavour.get_flavour_groups(
            bool(defn.strategies.any_flavour)
        )

        # We'll look for affine flavours > absolutely any flavour in every release
        # if any_flavour is true.  This is less expensive than performing
        # separate flavour passes across the whole release list for the common case.
        match = await self.__find_match(first_release, desired_flavour_groups)
        if not match:
            logger.info('looking for match in older releases')

            _remaining_tasks = []
            try:
                for release_task, _remaining_tasks in (
                    (t, g[o:])
                    # 3 groups of 3 run in parallel but processed in order
                    for b in batched(releases, 3)
                    for g in (
                        [
                            asyncio.create_task(self.__find_match(r, desired_flavour_groups))
                            for r in b
                        ],
                    )
                    for o, t in enumerate(g, start=1)
                ):
                    match = await release_task
                    if match:
                        break
            finally:
                if _remaining_tasks:
                    await cancel_tasks(_remaining_tasks)

        if match:
            release, asset = match
        else:
            raise R.PkgFilesNotMatching(defn.strategies)

        return PkgCandidate(
            id=str(project['id']),
            slug=project['full_name'].lower(),
            name=project['name'],
            description=project['description'] or '',
            url=project['html_url'],
            download_url=asset['url'],
            date_published=iso8601.parse_date(release['published_at']),
            version=release['tag_name'],
            changelog_url=as_plain_text_data_url(release['body']),
        )

    @classmethod
    async def catalogue(cls, web_client: ClientSessionType) -> AsyncIterator[CatalogueEntry]:
        import csv
        from io import StringIO

        logger.debug(f'retrieving {cls.__generated_catalogue_csv_url}')

        async with web_client.get(
            cls.__generated_catalogue_csv_url, raise_for_status=True
        ) as response:
            catalogue_csv = await response.text()

        dict_reader = csv.DictReader(StringIO(catalogue_csv))

        id_keys = [
            (k, k.removesuffix('_id')) for k in dict_reader.fieldnames or [] if k.endswith('_id')
        ]

        def extract_flavours(flavours: str):
            for flavour in filter(None, flavours.split(',')):
                try:
                    release_json_flavor = _PackagerReleaseJsonFlavor(flavour)
                except ValueError:
                    continue
                else:
                    yield Flavour.from_flavour_keyed_enum(release_json_flavor)

        for entry in dict_reader:
            yield CatalogueEntry(
                source=cls.metadata.id,
                id=entry['id'],
                slug=entry['full_name'].lower(),
                name=entry['name'],
                url=entry['url'],
                game_flavours=frozenset(extract_flavours(entry['flavors'])),
                download_count=1,
                last_updated=datetime.fromisoformat(entry['last_updated']),
                same_as=[AddonKey(source=s, id=i) for k, s in id_keys for i in (entry[k],) if i],
            )
