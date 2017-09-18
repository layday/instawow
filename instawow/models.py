
from datetime import datetime
import json
from pathlib import Path

import pydantic
from sqlalchemy import Column, String, DateTime, Enum, ForeignKeyConstraint, \
                       TypeDecorator, or_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship


def _declarative_constructor(self, **kwargs):
    for k, v in _BaseCoercer.__members__[self.__class__]\
                            .parse_obj(kwargs):
        setattr(self, k, v)


ModelBase = declarative_base(constructor=_declarative_constructor)


class _MetaBase(pydantic.BaseModel.__class__):

    __members__ = {}

    def __new__(mcs, name, bases, namespace, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace)
        if 'coerces' in kwargs:
            mcs.__members__[kwargs['coerces']] = cls
        return cls


class _BaseCoercer(pydantic.BaseModel, metaclass=_MetaBase):
    """The coercer is used inside the declarative constructor to type-cast
    values _prior to_ inserts.  SQLAlchemy delegates this function to
    the DB API - see https://stackoverflow.com/a/8980982.  We need this to
    happen in advance to be able to compare values with their in-database
    equivalents without having to wrap every single one of them inside
    `str()` (yuck).  It also saves us the trouble of having to manually
    parse dates and the like.
    """

    class Config:
        allow_extra = True
        max_anystr_length = 2 ** 32


class _PathType(TypeDecorator):

    impl = String

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)

    def process_result_value(self, value, dialect):
        if value is not None:
            return Path(value)


class _JsonType(TypeDecorator):

    impl = String

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)


class _ConvenienceMethodsMixin:

    def insert(self, session):
        session.add(self)
        session.commit()
        return self

    def replace(self, session, other=None):
        if other:
            session.delete(other)
            session.commit()
        return self.insert(session)

    def delete(self, session):
        session.delete(self)
        session.commit()


class Pkg(ModelBase,
          _ConvenienceMethodsMixin):

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

    @classmethod
    def unique(cls, origin, id_or_slug, session):
        return session.query(cls).filter(cls.origin == origin,
                                         or_(cls.id == id_or_slug, cls.slug == id_or_slug))\
                      .first()


class _PkgCoercer(_BaseCoercer, coerces=Pkg):

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

    path = Column(_PathType, primary_key=True)  # TODO: migrate paths to basenames
    pkg_origin = Column(String, nullable=False)
    pkg_id = Column(String, nullable=False)


class _PkgFolderCoercer(_BaseCoercer, coerces=PkgFolder):

    path: Path


class PkgOptions(ModelBase):

    __tablename__ = 'pkg_options'
    __table_args__ = (ForeignKeyConstraint(['pkg_origin', 'pkg_id'],
                                           ['pkg.origin', 'pkg.id']),)

    strategy = Column(Enum('canonical', 'latest'), nullable=False)
    pkg_origin = Column(String, primary_key=True)
    pkg_id = Column(String, primary_key=True)


class _PkgOptionsCoercer(_BaseCoercer, coerces=PkgOptions):

    strategy: str


class CacheEntry(ModelBase,
                 _ConvenienceMethodsMixin):

    __tablename__ = 'cache'

    origin = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    date_updated = Column(DateTime)
    date_retrieved = Column(DateTime, nullable=False)
    contents = Column(_JsonType, nullable=False)


class _CacheEntryCoercer(_BaseCoercer, coerces=CacheEntry):

    origin: str
    id: str
    date_updated: datetime = None
    date_retrieved: datetime
    contents: str
