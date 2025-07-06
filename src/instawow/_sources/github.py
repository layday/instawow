from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from itertools import batched, tee, zip_longest
from typing import Any, Literal

from typing_extensions import TypedDict
from yarl import URL

from .. import config_ctx, http, http_ctx
from .._logging import logger
from .._utils.aio import cancel_tasks
from .._utils.web import as_plain_text_data_url, extract_byte_range_offset
from ..definitions import ChangelogFormat, Defn, SourceMetadata, Strategy
from ..resolvers import (
    AccessToken,
    BaseResolver,
    CatalogueEntryCandidate,
    HeadersIntent,
    PkgCandidate,
)
from ..results import PkgFilesMissing, PkgFilesNotMatching, PkgNonexistent
from ..wow_installations import (
    Flavour,
    FlavourVersions,
    get_compatible_flavours,
    to_flavour_versions,
    to_flavourful_enum,
)


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


class _PackagerReleaseJson(TypedDict):
    releases: list[_PackagerReleaseJson_Release]


class _PackagerReleaseJson_Release(TypedDict):
    # name: NotRequired[str]  # Added in https://github.com/BigWigsMods/packager/commit/7812bcd
    # version: NotRequired[str]  # As above
    filename: str
    nolib: bool
    metadata: list[_PackagerReleaseJson_Release_Metadata]


class _PackagerReleaseJson_Release_Metadata(TypedDict):
    flavor: _PackagerReleaseJsonFlavor
    interface: int


class _PackagerReleaseJsonFlavor(StrEnum):
    Retail = 'mainline'
    VanillaClassic = 'classic'
    TbcClassic = 'bcc'
    WrathClassic = 'wrath'
    CataClassic = 'cata'
    MistsClassic = 'mists'


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

    __api_url = URL('https://api.github.com/')
    __generated_catalogue_csv_url = (
        'https://raw.githubusercontent.com/layday/github-wow-addon-catalogue/main/addons.csv'
    )

    @AccessToken
    def access_token():
        return config_ctx.config().global_config.access_tokens.github, False

    def get_alias_from_url(self, url: URL):
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    def make_request_headers(self, intent: HeadersIntent | None = None):
        headers = dict[str, str]()

        headers['X-GitHub-Api-Version'] = '2022-11-28'

        if intent is HeadersIntent.Download:
            headers['Accept'] = 'application/octet-stream'
        else:
            headers['Accept'] = 'application/vnd.github+json'

        maybe_access_token = self.access_token.get()
        if maybe_access_token:
            headers['Authorization'] = f'token {maybe_access_token}'

        return headers

    async def __find_match_from_zip_contents(
        self,
        assets: list[_GithubRelease_Asset],
        desired_flavour: Flavour | None,
    ):
        import zipfile
        from io import BytesIO

        from aiohttp import hdrs

        from ..matchers import NORMALISED_FLAVOUR_TOC_EXTENSIONS
        from ..matchers.addon_toc import TocReader
        from ..pkg_archives import find_archive_addon_tocs

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

        download_headers = self.make_request_headers(HeadersIntent.Download)

        all_toc_extensions = tuple(
            i for s in NORMALISED_FLAVOUR_TOC_EXTENSIONS.values() for i in s
        )
        desired_toc_extensions = (
            NORMALISED_FLAVOUR_TOC_EXTENSIONS[desired_flavour]
            if desired_flavour
            else all_toc_extensions
        )

        matching_asset = None

        for candidate in candidates:
            logger.debug(f'Looking for match in zip file: {candidate["url"]}')

            addon_zip_stream = BytesIO()
            dynamic_addon_zip = None
            is_zip_complete = False

            download_url = candidate['url']

            # A large enough initial offset that we won't typically have to
            # resort to extracting the ECD.
            directory_offset = str(-25_000)

            for _ in range(2):
                logger.debug(f'Fetching {directory_offset} bytes from {candidate["name"]}')

                async with http_ctx.web_client().get(
                    download_url,
                    expire_after=http.CACHE_INDEFINITELY,
                    headers=download_headers | {hdrs.RANGE: f'bytes={directory_offset}'},
                ) as directory_range_response:
                    if not directory_range_response.ok:
                        # File size under 25 KB.
                        # The GH API incorrectly returns 501 instead of 416 Range Not Satisfiable.
                        if directory_range_response.status == 416 or (
                            directory_range_response.status == 501
                            and directory_range_response.reason == 'Unsupported client range'
                        ):
                            async with http_ctx.web_client().get(
                                download_url,
                                expire_after=http.CACHE_INDEFINITELY,
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
                logger.warning('Directory marker not found')
                continue

            toc_filenames = {
                n
                for n, h in find_archive_addon_tocs(f.filename for f in dynamic_addon_zip.filelist)
                if h in candidate['name']  # Folder name is a substring of zip name.
            }
            if not toc_filenames:
                continue

            if desired_flavour is None:
                matching_asset = candidate
                break

            flavour_from_toc_filename = any(
                n.lower().endswith(desired_toc_extensions) for n in toc_filenames
            )
            if flavour_from_toc_filename:
                matching_asset = candidate
                break

            try:
                main_toc_filename = min(
                    (n for n in toc_filenames if not n.lower().endswith(all_toc_extensions)),
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

                logger.debug(f'Fetching {main_toc_filename} from {candidate["name"]}')
                async with http_ctx.web_client().get(
                    download_url,
                    expire_after=http.CACHE_INDEFINITELY,
                    headers=download_headers
                    | {hdrs.RANGE: f'bytes={main_toc_file_offset}-{following_file_offset}'},
                    raise_for_status=True,
                ) as toc_file_range_response:
                    addon_zip_stream.seek(main_toc_file_offset)
                    addon_zip_stream.write(await toc_file_range_response.read())

            toc_content = dynamic_addon_zip.read(main_toc_filename)
            toc_reader = TocReader.from_bytes(toc_content)

            logger.debug(
                f'Found interface versions {toc_reader.interfaces!r} in {main_toc_filename}'
            )
            desired_flavour_versions = to_flavour_versions(desired_flavour)
            if toc_reader.interfaces and any(
                FlavourVersions.from_version_number(i) is desired_flavour_versions
                for i in toc_reader.interfaces
            ):
                matching_asset = candidate
                break

        return matching_asset

    async def __find_match_from_release_json(
        self,
        assets: list[_GithubRelease_Asset],
        release_json_asset: _GithubRelease_Asset,
        desired_flavour: Flavour | None,
    ):
        from .._utils.attrs import simple_converter

        logger.debug(f'Looking for match in release.json: {release_json_asset["url"]}')

        download_headers = self.make_request_headers(HeadersIntent.Download)

        async with http_ctx.web_client().get(
            release_json_asset['url'],
            expire_after=timedelta(days=1),
            headers=download_headers,
            raise_for_status=True,
        ) as response:
            packager_metadata_dict = await response.json(
                content_type=None  # application/octet-stream
            )

        packager_metadata = simple_converter().structure(
            packager_metadata_dict, _PackagerReleaseJson
        )

        subreleases = packager_metadata['releases']
        if not subreleases:
            return None

        if desired_flavour:
            desired_flavour_versions = to_flavour_versions(desired_flavour)
            desired_release_json_flavor = to_flavourful_enum(
                desired_flavour, _PackagerReleaseJsonFlavor
            )

            def is_compatible(release: _PackagerReleaseJson_Release):
                for metadata in release['metadata']:
                    if metadata['flavor'] == desired_release_json_flavor:
                        if (
                            FlavourVersions.from_version_number(metadata['interface'])
                            is desired_flavour_versions
                        ):
                            return True

                        logger.info(
                            f'Flavor and interface mismatch: {(metadata["interface"], desired_flavour)}'
                        )

                return False

        else:

            def is_compatible(release: _PackagerReleaseJson_Release) -> bool:
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
        desired_flavours: tuple[Flavour, ...] | tuple[*tuple[Flavour, ...], None],
    ):
        assets = release['assets']
        release_json = next(
            (a for a in assets if a['name'] == 'release.json' and a['state'] == 'uploaded'),
            None,
        )
        matcher = (
            partial(self.__find_match_from_release_json, assets, release_json)
            if release_json
            else partial(self.__find_match_from_zip_contents, assets)
        )
        for desired_flavour in desired_flavours:
            asset = await matcher(desired_flavour)
            if asset:
                return (release, asset)

    async def resolve_one(self, defn: Defn, metadata: None):
        github_headers = self.make_request_headers()

        id_or_alias = defn.id or defn.alias
        if id_or_alias.isdigit():
            repo_url = self.__api_url / 'repositories' / id_or_alias
        else:
            repo_url = self.__api_url / 'repos' / defn.alias

        async def get_project():
            async with http_ctx.web_client().get(
                repo_url, expire_after=timedelta(hours=1), headers=github_headers
            ) as response:
                if response.status == 404:
                    raise PkgNonexistent
                response.raise_for_status()

                project: _GithubRepo = await response.json()
                return project

        version_eq = defn.strategies[Strategy.VersionEq]
        if version_eq:
            release_url = repo_url / 'releases/tags' / version_eq
        else:
            # Includes pre-releases
            release_url = (repo_url / 'releases').with_query(
                # Default is 30 but we're more conservative
                per_page='10'
            )

        async def get_releases():
            async with http_ctx.web_client().get(
                release_url, expire_after=timedelta(minutes=5), headers=github_headers
            ) as response:
                if response.status == 404:
                    raise PkgFilesMissing('no releases found')
                response.raise_for_status()

                release_json: _GithubRelease | list[_GithubRelease] = await response.json()
                if not isinstance(release_json, list):
                    release_json = [release_json]
                return release_json

        releases_coro = asyncio.create_task(get_releases())
        try:
            project = await get_project()
        except BaseException:
            await cancel_tasks([releases_coro])
            raise

        # Only users with push access will get draft releases
        # but let's filter them out just in case.
        releases = [r for r in await releases_coro if r['draft'] is False]

        # Allow pre-releases only if no stable releases exist or explicitly opted into.
        if not defn.strategies[Strategy.AnyReleaseType] and any(
            r['prerelease'] is False for r in releases
        ):
            releases = (r for r in releases if r['prerelease'] is False)

        releases = iter(releases)
        first_release = next(releases, None)
        if first_release is None:
            raise PkgFilesNotMatching(defn.strategies)

        desired_flavours = get_compatible_flavours(
            config_ctx.config().track, defn.strategies[Strategy.AnyFlavour]
        )

        # We'll look for affine flavours > absolutely any flavour in every release
        # if ``Strategy.AnyFlavour`` is set.  This is less expensive than performing
        # separate flavour passes across the whole release list for the common case.
        match = await self.__find_match(first_release, desired_flavours)
        if not match:
            logger.info('Looking for match in older releases')

            _remaining_tasks = []
            try:
                for release_task, _remaining_tasks in (
                    (t, g[o:])
                    # 3 groups of 3 run in parallel but processed in order
                    for b in batched(releases, 3)
                    for g in (
                        [asyncio.create_task(self.__find_match(r, desired_flavours)) for r in b],
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
            raise PkgFilesNotMatching(defn.strategies)

        return PkgCandidate(
            id=str(project['id']),
            slug=project['full_name'].lower(),
            name=project['name'],
            description=project['description'] or '',
            url=project['html_url'],
            download_url=asset['url'],
            date_published=datetime.fromisoformat(release['published_at']),
            version=release['tag_name'],
            changelog_url=as_plain_text_data_url(release['body']),
        )

    async def catalogue(self):
        import csv
        from io import StringIO

        supported_flavours = {
            to_flavourful_enum(f, _PackagerReleaseJsonFlavor): f for f in Flavour
        }

        logger.debug(f'Retrieving {self.__generated_catalogue_csv_url}')

        async with http_ctx.web_client().get(
            self.__generated_catalogue_csv_url, raise_for_status=True
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
                    if release_json_flavor in supported_flavours:
                        yield supported_flavours[release_json_flavor]

        for entry in dict_reader:
            yield CatalogueEntryCandidate(
                id=entry['id'],
                slug=entry['full_name'].lower(),
                name=entry['name'],
                url=entry['url'],
                game_flavours=frozenset(extract_flavours(entry['flavors'])),
                download_count=0,
                last_updated=datetime.fromisoformat(entry['last_updated']),
                same_as=[{'source': s, 'id': i} for k, s in id_keys for i in (entry[k],) if i],
            )
