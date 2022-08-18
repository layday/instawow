from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from datetime import datetime
from functools import lru_cache
from itertools import tee, zip_longest

import iso8601
from loguru import logger
from typing_extensions import Literal, NotRequired as N, TypedDict
from yarl import URL

from .. import _deferred_types, models, results as R
from ..cataloguer import BaseCatalogueEntry, CatalogueSameAs
from ..common import ChangelogFormat, Flavour, FlavourVersion, SourceMetadata, Strategy
from ..resolvers import BaseResolver, Defn, format_data_changelog
from ..utils import StrEnum, TocReader, extract_byte_range_offset, find_addon_zip_tocs


# Not exhaustive (as you might've guessed).  Reference:
# https://docs.github.com/en/rest/reference/repos
class _GithubRepo(TypedDict):
    name: str  # the repo in user-or-org/repo
    full_name: str  # user-or-org/repo
    description: str | None
    html_url: str


class _GithubRelease(TypedDict):
    tag_name: str  # Hopefully the version
    published_at: str  # ISO datetime
    assets: list[_GithubRelease_Asset]
    body: str
    draft: bool
    prerelease: bool


class _GithubRelease_Asset(TypedDict):
    name: str  # filename
    content_type: str  # mime type
    state: Literal['starter', 'uploaded']
    browser_download_url: str


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
    retail = 'mainline'
    vanilla_classic = 'classic'
    burning_crusade_classic = 'bcc'
    wrath_classic = 'wrath'


class GithubResolver(BaseResolver):
    metadata = SourceMetadata(
        id='github',
        name='GitHub',
        strategies=frozenset({Strategy.default, Strategy.latest, Strategy.version}),
        changelog_format=ChangelogFormat.markdown,
    )

    _repos_api_url = URL('https://api.github.com/repos')

    _generated_catalogue_csv_url = (
        'https://raw.githubusercontent.com/layday/github-wow-addon-catalogue/main/addons.csv'
    )

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    @staticmethod
    @lru_cache(1)
    def _make_auth_headers(access_token: str | None):
        return {'Authorization': f'token {access_token}'} if access_token else {}

    async def _find_matching_asset_from_zip_contents(self, assets: list[_GithubRelease_Asset]):
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

        from io import BytesIO
        import zipfile

        from aiohttp import hdrs

        from ..matchers import NORMALISED_FLAVOUR_TOC_SUFFIXES

        github_headers = self._make_auth_headers(
            self._manager.config.global_config.access_tokens.github
        )

        matching_asset = None

        for candidate in candidates:
            addon_zip_stream = BytesIO()
            dynamic_addon_zip = None
            is_zip_complete = False

            download_url = candidate['browser_download_url']

            # A large enough initial offset that we won't typically have to
            # resort to extracting the ECD.
            directory_offset = str(-25_000)

            for _ in range(2):
                logger.debug(f'fetching {directory_offset} from {candidate["name"]}')

                async with self._manager.web_client.wrapped.get(
                    download_url,
                    headers={**github_headers, hdrs.RANGE: f'bytes={directory_offset}'},
                ) as directory_range_response:
                    if not directory_range_response.ok:
                        # File size under 25 KB.
                        if directory_range_response.status == 416:  # Range Not Satisfiable
                            async with self._manager.web_client.get(
                                download_url,
                                {'days': 30},
                                headers=github_headers,
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
                            from zipfile import _ECD_OFFSET, _EndRecData  # pyright: ignore

                            end_rec_data = _EndRecData(addon_zip_stream)  # pyright: ignore
                            directory_offset = f'{end_rec_data[_ECD_OFFSET]}-'
                        else:
                            break

            if dynamic_addon_zip is None:
                logger.warning('directory marker not found')
                continue

            toc_filenames = {
                n
                for n, h in find_addon_zip_tocs(f.filename for f in dynamic_addon_zip.filelist)
                if h in candidate['name']  # Folder name is a substring of zip name.
            }
            if not toc_filenames:
                continue

            game_flavour_from_toc_filename = any(
                n.lower().endswith(
                    NORMALISED_FLAVOUR_TOC_SUFFIXES[self._manager.config.game_flavour]
                )
                for n in toc_filenames
            )
            if game_flavour_from_toc_filename:
                matching_asset = candidate
                break

            try:
                main_toc_filename = min(
                    (
                        n
                        for n in toc_filenames
                        if not n.lower().endswith(
                            tuple(i for s in NORMALISED_FLAVOUR_TOC_SUFFIXES.values() for i in s)
                        )
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
                async with self._manager.web_client.get(
                    download_url,
                    {'days': 30},
                    headers={
                        **github_headers,
                        hdrs.RANGE: f'bytes={main_toc_file_offset}-{following_file_offset}',
                    },
                    raise_for_status=True,
                ) as toc_file_range_response:
                    addon_zip_stream.seek(main_toc_file_offset)
                    addon_zip_stream.write(await toc_file_range_response.read())

            toc_file_text = dynamic_addon_zip.read(main_toc_filename).decode('utf-8-sig')
            toc_reader = TocReader(toc_file_text)
            interface_version = toc_reader['Interface']
            logger.debug(f'found interface version {interface_version!r} in {main_toc_filename}')
            if interface_version and self._manager.config.game_flavour.to_flavour_keyed_enum(
                FlavourVersion
            ).is_within_version(int(interface_version)):
                matching_asset = candidate
                break

        return matching_asset

    async def _find_matching_asset_from_release_json(
        self, assets: list[_GithubRelease_Asset], release_json_asset: _GithubRelease_Asset
    ):
        github_headers = self._make_auth_headers(
            self._manager.config.global_config.access_tokens.github
        )

        async with self._manager.web_client.get(
            release_json_asset['browser_download_url'],
            {'days': 1},
            headers=github_headers,
            raise_for_status=True,
        ) as response:
            packager_metadata: _PackagerReleaseJson = await response.json()

        releases = packager_metadata['releases']
        if not releases:
            return None

        wanted_flavour = self._manager.config.game_flavour.to_flavour_keyed_enum(
            _PackagerReleaseJsonFlavor
        )
        matching_release = next(
            (
                r
                for r in releases
                if r['nolib'] is False
                and any(m['flavor'] == wanted_flavour for m in r['metadata'])
            ),
            None,
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

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        github_headers = self._make_auth_headers(
            self._manager.config.global_config.access_tokens.github
        )

        repo_url = self._repos_api_url / defn.alias
        async with self._manager.web_client.get(
            repo_url, {'hours': 1}, headers=github_headers
        ) as response:
            if response.status == 404:
                raise R.PkgNonexistent
            response.raise_for_status()
            project: _GithubRepo = await response.json()

        if defn.strategy is Strategy.version:
            assert defn.version
            release_url = repo_url / 'releases/tags' / defn.version
        else:
            # Includes pre-releases
            release_url = (repo_url / 'releases').with_query(
                # Default is 30 but we're more conservative
                per_page='10'
            )

        async with self._manager.web_client.get(
            release_url, {'minutes': 5}, headers=github_headers
        ) as response:
            if response.status == 404:
                raise R.PkgFileUnavailable('release not found')
            response.raise_for_status()

            response_json = await response.json()
            if defn.strategy is Strategy.version:
                response_json = [response_json]
            releases: Iterable[_GithubRelease] = response_json

        # Only users with push access will receive draft releases
        # but let's filter them out just in case.
        releases = (r for r in releases if r['draft'] is False)

        if defn.strategy is not Strategy.latest:
            releases = (r for r in releases if r['prerelease'] is False)

        seen_release_json = False
        for release in releases:
            assets = release['assets']
            matching_asset = None

            release_json = next(
                (a for a in assets if a['name'] == 'release.json' and a['state'] == 'uploaded'),
                None,
            )
            if not seen_release_json and release_json is None:
                matching_asset = await self._find_matching_asset_from_zip_contents(assets)
            elif release_json is not None:
                seen_release_json = True
                matching_asset = await self._find_matching_asset_from_release_json(
                    assets, release_json
                )

            if matching_asset is not None:
                break

        else:
            raise R.PkgFileUnavailable(f'no files matching {self._manager.config.game_flavour}')

        return models.Pkg(
            source=self.metadata.id,
            id=project['full_name'],
            slug=project['full_name'].lower(),
            name=project['name'],
            description=project['description'] or '',
            url=project['html_url'],
            download_url=matching_asset['browser_download_url'],
            date_published=iso8601.parse_date(release['published_at']),
            version=release['tag_name'],
            changelog_url=format_data_changelog(release['body']),
            options=models.PkgOptions(
                strategy=defn.strategy,
            ),
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        import csv
        from io import StringIO

        logger.debug(f'retrieving {cls._generated_catalogue_csv_url}')

        async with web_client.get(
            cls._generated_catalogue_csv_url, raise_for_status=True
        ) as response:
            catalogue_csv = await response.text()

        dict_reader = csv.DictReader(StringIO(catalogue_csv))
        id_keys = [
            (k, k[: -len('_id')]) for k in dict_reader.fieldnames or [] if k.endswith('_id')
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
            yield BaseCatalogueEntry(
                source=cls.metadata.id,
                id=entry['full_name'],
                slug=entry['full_name'].lower(),
                name=entry['name'],
                url=entry['url'],
                game_flavours=frozenset(extract_flavours(entry['flavors'])),
                download_count=1,
                last_updated=datetime.fromisoformat(entry['last_updated']),
                same_as=[
                    CatalogueSameAs(source=s, id=i) for k, s in id_keys for i in (entry[k],) if i
                ],
            )
