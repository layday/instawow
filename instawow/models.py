
from __future__ import annotations

__all__ = ('ModelBase',
           'Pkg',
           'PkgFolder',
           'PkgOptions',
           'PkgCoercer',
           'PkgFolderCoercer',
           'PkgOptionsCoercer',
           'should_migrate')

from datetime import datetime
from typing import TYPE_CHECKING

import pydantic
from sqlalchemy import Column, ForeignKeyConstraint, DateTime, String
import sqlalchemy.exc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

if TYPE_CHECKING:
    import sqlalchemy.base


def _declarative_constructor(self, **kwargs):
    intermediate_obj = _COERCERS[self.__class__].parse_obj(kwargs)
    for k, v in intermediate_obj:
        setattr(self, k, v)


_declarative_constructor.__name__ = '__init__'

ModelBase = declarative_base(constructor=_declarative_constructor)


class _BaseCoercer(pydantic.BaseModel):
    """The coercer is used inside the declarative constructor to type-cast
    values _prior to_ inserts.  SQLAlchemy delegates this function to
    the DB API -- see https://stackoverflow.com/a/8980982.  We need this to
    happen in advance to be able to compare values with their in-database
    counterparts.  It also saves us the trouble of having to manually
    parse dates and the like.
    """

    class Config:
        extra = pydantic.Extra.allow
        max_anystr_length = 2 ** 32


class Pkg(ModelBase):

    __tablename__ = 'pkg'

    origin = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    slug = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    url = Column(String, nullable=False)
    file_id = Column(String, nullable=False)
    download_url = Column(String, nullable=False)
    date_published = Column(DateTime, nullable=False)
    version = Column(String, nullable=False)
    folders = relationship('PkgFolder', cascade='all, delete-orphan',
                           backref='pkg')
    options = relationship('PkgOptions', cascade='all, delete-orphan',
                           uselist=False)


class PkgCoercer(_BaseCoercer):

    origin: str
    id: str
    slug: str
    name: str
    description: str
    url: str
    file_id: str
    download_url: str
    date_published: datetime
    version: str


class PkgFolder(ModelBase):

    __tablename__ = 'pkg_folder'
    __table_args__ = (ForeignKeyConstraint(['pkg_origin', 'pkg_id'],
                                           ['pkg.origin', 'pkg.id']),)

    name = Column(String, primary_key=True)
    pkg_origin = Column(String, nullable=False)
    pkg_id = Column(String, nullable=False)


class PkgFolderCoercer(_BaseCoercer):

    name: str


class PkgOptions(ModelBase):

    __tablename__ = 'pkg_options'
    __table_args__ = (ForeignKeyConstraint(['pkg_origin', 'pkg_id'],
                                           ['pkg.origin', 'pkg.id']),)

    strategy = Column(String, nullable=False)
    pkg_origin = Column(String, primary_key=True)
    pkg_id = Column(String, primary_key=True)


class PkgOptionsCoercer(_BaseCoercer):

    strategy: str


_COERCERS = {Pkg: PkgCoercer,
             PkgFolder: PkgFolderCoercer,
             PkgOptions: PkgOptionsCoercer}


def should_migrate(engine: sqlalchemy.base.Engine, version: str) -> bool:
    """Check if the database version is the same as `version`;
    if not a migration would be required.
    """
    with engine.begin() as conn:
        try:
            current = conn.execute('SELECT version_num '
                                   'FROM alembic_version '
                                   'WHERE version_num = (?)', version).scalar()
        except sqlalchemy.exc.OperationalError:
            return True
        else:
            if not current:
                return True
    return False
