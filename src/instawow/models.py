from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import typing
from typing import Any, Mapping

from pydantic import BaseModel
import sqlalchemy as sa
import sqlalchemy.future as sa_future

from . import db
from .common import Strategy


@contextmanager
def _faux_transaction(connection: sa_future.Connection):
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


class _PkgOptions(BaseModel):
    strategy: Strategy


class _PkgFolder(BaseModel):
    name: str


class _PkgDep(BaseModel):
    id: str


class _PkgLoggedVersion(BaseModel):
    version: str
    install_time: datetime


class Pkg(BaseModel):
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
    options: _PkgOptions  # pkg_options
    folders: typing.List[_PkgFolder] = []  # pkg_folder
    deps: typing.List[_PkgDep] = []  # pkg_dep
    logged_versions: typing.List[_PkgLoggedVersion] = []  # pkg_version_log

    @classmethod
    def from_row_mapping(
        cls, connection: sa_future.Connection, row_mapping: Mapping[str, Any]
    ) -> Pkg:
        source_and_id = {'pkg_source': row_mapping['source'], 'pkg_id': row_mapping['id']}
        return cls.parse_obj(
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
            }
        )

    def insert(self, connection: sa_future.Connection) -> None:
        values = self.dict()
        source_and_id = {'pkg_source': values['source'], 'pkg_id': values['id']}
        with _faux_transaction(connection):
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
        source_and_id = {'pkg_source': self.source, 'pkg_id': self.id}
        with _faux_transaction(connection):
            connection.execute(sa.delete(db.pkg_dep).filter_by(**source_and_id))
            connection.execute(sa.delete(db.pkg_folder).filter_by(**source_and_id))
            connection.execute(sa.delete(db.pkg_options).filter_by(**source_and_id))
            connection.execute(sa.delete(db.pkg).filter_by(source=self.source, id=self.id))

    # Make the model hashable again
    __eq__ = object.__eq__
    __hash__ = object.__hash__  # type: ignore


class PkgList(BaseModel):
    __root__: typing.List[Pkg]
