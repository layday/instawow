from __future__ import annotations

from datetime import datetime
import typing
from typing import Any, Mapping

from pydantic import BaseModel
import sqlalchemy as sa
import sqlalchemy.future as sa_future
from typing_extensions import TypeAlias, TypeGuard

from . import db
from .common import Strategy


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
        return cls.parse_obj(
            {
                **row_mapping,
                'folders': connection.execute(
                    sa.select(db.pkg_folder.c.name).filter_by(
                        pkg_source=row_mapping['source'], pkg_id=row_mapping['id']
                    )
                )
                .mappings()
                .all(),
                'options': connection.execute(
                    sa.select(db.pkg_options.c.strategy).filter_by(
                        pkg_source=row_mapping['source'], pkg_id=row_mapping['id']
                    )
                )
                .mappings()
                .one(),
                'deps': connection.execute(
                    sa.select(db.pkg_dep.c.id).filter_by(
                        pkg_source=row_mapping['source'], pkg_id=row_mapping['id']
                    )
                )
                .mappings()
                .all(),
                'logged_versions': connection.execute(
                    sa.select(db.pkg_version_log)
                    .filter_by(pkg_source=row_mapping['source'], pkg_id=row_mapping['id'])
                    .order_by(db.pkg_version_log.c.install_time.desc())
                    .limit(10)
                )
                .mappings()
                .all(),
            }
        )

    def insert(self, connection: sa_future.Connection) -> None:
        pkg_dict = self.dict()
        connection.execute(
            sa.insert(db.pkg),
            [pkg_dict],
        )
        connection.execute(
            sa.insert(db.pkg_folder),
            [
                {**f, 'pkg_source': pkg_dict['source'], 'pkg_id': pkg_dict['id']}
                for f in pkg_dict['folders']
            ],
        )
        connection.execute(
            sa.insert(db.pkg_options),
            [
                {
                    **pkg_dict['options'],
                    'pkg_source': pkg_dict['source'],
                    'pkg_id': pkg_dict['id'],
                }
            ],
        )
        if pkg_dict['deps']:
            connection.execute(
                sa.insert(db.pkg_dep),
                [
                    {**f, 'pkg_source': pkg_dict['source'], 'pkg_id': pkg_dict['id']}
                    for f in pkg_dict['deps']
                ],
            )
        connection.execute(
            sa.insert(db.pkg_version_log).prefix_with('OR IGNORE'),
            [
                {
                    'version': pkg_dict['version'],
                    'pkg_source': pkg_dict['source'],
                    'pkg_id': pkg_dict['id'],
                }
            ],
        )
        connection.commit()

    def delete(self, connection: sa_future.Connection) -> None:
        connection.execute(
            sa.delete(db.pkg_dep).filter_by(pkg_source=self.source, pkg_id=self.id),
        )
        connection.execute(
            sa.delete(db.pkg_folder).filter_by(pkg_source=self.source, pkg_id=self.id),
        )
        connection.execute(
            sa.delete(db.pkg_options).filter_by(pkg_source=self.source, pkg_id=self.id),
        )
        connection.execute(
            sa.delete(db.pkg).filter_by(source=self.source, id=self.id),
        )
        connection.commit()

    # Make the model hashable again
    __eq__ = object.__eq__
    __hash__ = object.__hash__  # type: ignore


class PkgList(BaseModel):
    __root__: typing.List[Pkg]


def is_pkg(value: object) -> TypeGuard[Pkg]:
    return isinstance(value, Pkg)


PkgLike: TypeAlias = Any
