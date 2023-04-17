from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

import sqlalchemy as sa
from attrs import asdict, frozen
from cattrs import Converter
from typing_extensions import Self

from . import db
from .common import Defn, StrategyValues

_db_pkg_converter = Converter()
_db_pkg_converter.register_structure_hook(datetime, lambda d, _: d)


@frozen(kw_only=True)
class PkgOptions:
    any_flavour: bool
    any_release_type: bool
    version_eq: bool

    @classmethod
    def from_strategy_values(cls, strategies: StrategyValues) -> Self:
        return cls(
            **{k: bool(v) for k, v in asdict(strategies).items()},
        )


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
    folders: list[PkgFolder] = []  # pkg_folder
    deps: list[PkgDep] = []  # pkg_dep
    logged_versions: list[PkgLoggedVersion] = []  # pkg_version_log

    @classmethod
    def from_row_mapping(
        cls, connection: sa.Connection, row_mapping: Mapping[str, object]
    ) -> Self:
        source_and_id = {'pkg_source': row_mapping['source'], 'pkg_id': row_mapping['id']}
        return _db_pkg_converter.structure(
            {
                **row_mapping,
                'options': connection.execute(sa.select(db.pkg_options).filter_by(**source_and_id))
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

    def insert(self, transaction: sa.Connection) -> None:
        values = asdict(self)
        source_and_id = {'pkg_source': values['source'], 'pkg_id': values['id']}

        transaction.execute(sa.insert(db.pkg), [values])
        transaction.execute(
            sa.insert(db.pkg_folder), [{**f, **source_and_id} for f in values['folders']]
        )
        transaction.execute(sa.insert(db.pkg_options), [{**values['options'], **source_and_id}])
        if values['deps']:
            transaction.execute(
                sa.insert(db.pkg_dep), [{**d, **source_and_id} for d in values['deps']]
            )
        transaction.execute(
            sa.insert(db.pkg_version_log).prefix_with('OR IGNORE'),
            [{'version': values['version'], **source_and_id}],
        )

    def delete(self, transaction: sa.Connection) -> None:
        transaction.execute(sa.delete(db.pkg).filter_by(source=self.source, id=self.id))

    def to_defn(self) -> Defn:
        return Defn(
            source=self.source,
            alias=self.slug,
            id=self.id,
            strategies=StrategyValues(
                any_flavour=self.options.any_flavour or None,
                any_release_type=self.options.any_release_type or None,
                version_eq=self.version if self.options.version_eq else None,
            ),
        )
