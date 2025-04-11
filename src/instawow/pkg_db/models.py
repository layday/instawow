from __future__ import annotations

import datetime as dt
from functools import lru_cache

import cattrs
from attrs import asdict, frozen
from typing_extensions import TypedDict

from .. import resolvers
from ..definitions import Defn, Strategies, Strategy
from . import Connection, Row


def _structure_datetime(value: str | dt.datetime, value_type: type):
    match value:
        case dt.datetime():
            if value.tzinfo != dt.UTC:
                raise ValueError('``datetime`` must be in UTC')
            return value
        case _:
            return dt.datetime.fromisoformat(value).replace(tzinfo=dt.UTC)


def _unstructure_datetime(value: dt.datetime):
    if value.tzinfo != dt.UTC:
        raise ValueError('``datetime`` must be in UTC')

    return value.astimezone(dt.UTC).replace(tzinfo=None).isoformat(' ')


@lru_cache(1)
def make_db_converter():
    converter = cattrs.Converter()
    converter.register_structure_hook(dt.datetime, _structure_datetime)
    converter.register_unstructure_hook(dt.datetime, _unstructure_datetime)
    return converter


@frozen(kw_only=True)
class PkgOptions:
    any_flavour: bool
    any_release_type: bool
    version_eq: bool


@frozen(kw_only=True)
class PkgFolder:
    name: str


@frozen(kw_only=True)
class PkgDep:
    id: str


@frozen(kw_only=True)
class PkgLoggedVersion:
    version: str
    install_time: dt.datetime


@frozen(kw_only=True, eq=False)
class Pkg:
    source: str
    id: str
    slug: str
    name: str
    description: str
    url: str
    download_url: str
    date_published: dt.datetime
    version: str
    changelog_url: str
    options: PkgOptions  # pkg_options
    folders: list[PkgFolder]  # pkg_folder
    deps: list[PkgDep]  # pkg_dep

    def to_defn(self) -> Defn:
        return Defn(
            source=self.source,
            alias=self.slug,
            id=self.id,
            strategies=Strategies(
                asdict(  # pyright: ignore[reportArgumentType]
                    self.options,
                    value_serializer=lambda _, a, v: self.version
                    if a.name == Strategy.VersionEq and v is True
                    else v or None,
                )
            ),
        )


def build_pkg_from_pkg_candidate(
    defn: Defn,
    pkg_candidate: resolvers.PkgCandidate,
    *,
    folders: list[TypedDict[{'name': str}]],
) -> Pkg:
    return make_db_converter().structure(
        {
            'deps': [],
        }
        | pkg_candidate
        | {
            'source': defn.source,
            'options': {k: bool(v) for k, v in defn.strategies.items()},
            'folders': folders,
        },
        Pkg,
    )


def build_pkg_from_row_mapping(connection: Connection, row_mapping: Row) -> Pkg:
    fk = {'pkg_source': row_mapping['source'], 'pkg_id': row_mapping['id']}
    return make_db_converter().structure(
        {
            **row_mapping,
            'options': connection.execute(
                """
                SELECT any_flavour, any_release_type, version_eq
                FROM pkg_options
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                """,
                fk,
            ).fetchone(),
            'folders': connection.execute(
                """
                SELECT name
                FROM pkg_folder
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                """,
                fk,
            ).fetchall(),
            'deps': connection.execute(
                """
                SELECT id
                FROM pkg_dep
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                """,
                fk,
            ).fetchall(),
        },
        Pkg,
    )
