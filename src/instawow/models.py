from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import typing
from typing import Any

from attrs import asdict, frozen
from cattrs import GenConverter
from cattrs.preconf.json import configure_converter
import sqlalchemy as sa
import sqlalchemy.future as sa_future

from . import db
from .common import Strategy

pkg_converter = GenConverter()
configure_converter(pkg_converter)

_db_pkg_converter = GenConverter()
_db_pkg_converter.register_structure_hook(datetime, lambda d, _: d)


@frozen(kw_only=True)
class PkgOptions:
    strategy: Strategy


@frozen(kw_only=True)
class PkgFolder:
    name: str


@frozen(kw_only=True)
class PkgDep:
    id: str


@frozen(kw_only=True)
class PkgLoggedVersion:
    version: str
    install_time: datetime


@frozen(kw_only=True, eq=False)
class Pkg:
    source: str
    id: str
    slug: str
    name: str
    description: str
    url: str
    download_url: str
    date_published: datetime
    version: str
    changelog_url: str
    options: PkgOptions  # pkg_options
    folders: typing.List[PkgFolder] = []  # pkg_folder
    deps: typing.List[PkgDep] = []  # pkg_dep
    logged_versions: typing.List[PkgLoggedVersion] = []  # pkg_version_log

    @classmethod
    def from_row_mapping(
        cls, connection: sa_future.Connection, row_mapping: Mapping[str, Any]
    ) -> Pkg:
        source_and_id = {'pkg_source': row_mapping['source'], 'pkg_id': row_mapping['id']}
        return _db_pkg_converter.structure(
            {
                **row_mapping,
                'options': connection.execute(
                    sa.select(db.pkg_options.c.strategy).filter_by(**source_and_id)
                )
                .mappings()
                .one(),
                'folders': connection.execute(
                    sa.select(db.pkg_folder.c.name).filter_by(**source_and_id)
                )
                .mappings()
                .all(),
                'deps': connection.execute(sa.select(db.pkg_dep.c.id).filter_by(**source_and_id))
                .mappings()
                .all(),
                'logged_versions': connection.execute(
                    sa.select(db.pkg_version_log)
                    .filter_by(**source_and_id)
                    .order_by(db.pkg_version_log.c.install_time.desc())
                    .limit(10)
                )
                .mappings()
                .all(),
            },
            cls,
        )

    def insert(self, connection: sa_future.Connection) -> None:
        values = asdict(self)
        source_and_id = {'pkg_source': values['source'], 'pkg_id': values['id']}
        with db.faux_transact(connection):
            connection.execute(sa.insert(db.pkg), [values])
            connection.execute(
                sa.insert(db.pkg_folder), [{**f, **source_and_id} for f in values['folders']]
            )
            connection.execute(sa.insert(db.pkg_options), [{**values['options'], **source_and_id}])
            if values['deps']:
                connection.execute(
                    sa.insert(db.pkg_dep), [{**d, **source_and_id} for d in values['deps']]
                )
            connection.execute(
                sa.insert(db.pkg_version_log).prefix_with('OR IGNORE'),
                [{'version': values['version'], **source_and_id}],
            )

    def delete(self, connection: sa_future.Connection) -> None:
        with db.faux_transact(connection):
            connection.execute(sa.delete(db.pkg).filter_by(source=self.source, id=self.id))
