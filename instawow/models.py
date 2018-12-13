
from datetime import datetime
from pathlib import Path

import pydantic
from sqlalchemy import (Column, String, DateTime, Enum,
                        ForeignKeyConstraint, TypeDecorator)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship


def _declarative_constructor(self, **kwargs):
    for k, v in _coerces.coercers[self.__class__]\
                        .parse_obj(kwargs):
        setattr(self, k, v)


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
        allow_extra = True
        max_anystr_length = 2 ** 32


class _coerces:

    coercers = {}

    def __new__(cls, model):
        def wrapper(coercer):
            cls.coercers[model] = coercer
            return coercer
        return wrapper


class _PathType(TypeDecorator):

    impl = String

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is not None:
            return Path(value)


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


@_coerces(Pkg)
class _PkgCoercer(_BaseCoercer):

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

    path = Column(_PathType, primary_key=True)
    pkg_origin = Column(String, nullable=False)
    pkg_id = Column(String, nullable=False)


@_coerces(PkgFolder)
class _PkgFolderCoercer(_BaseCoercer):

    path: Path


class PkgOptions(ModelBase):

    __tablename__ = 'pkg_options'
    __table_args__ = (ForeignKeyConstraint(['pkg_origin', 'pkg_id'],
                                           ['pkg.origin', 'pkg.id']),)

    strategy = Column(Enum('canonical', 'latest'), nullable=False)
    pkg_origin = Column(String, primary_key=True)
    pkg_id = Column(String, primary_key=True)


@_coerces(PkgOptions)
class _PkgOptionsCoercer(_BaseCoercer):

    strategy: str
