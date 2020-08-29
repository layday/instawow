from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, List, Type, cast

import pydantic
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    and_,
    exc,
    func,
    inspect,
)
from sqlalchemy.ext.declarative import DeclarativeMeta, as_declarative
from sqlalchemy.orm import object_session, relationship


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
        orm_mode = True


class _BaseTableMeta(DeclarativeMeta):
    def __init__(cls, *args: Any) -> None:
        super().__init__(*args)
        try:
            inspector = inspect(cls)
        except exc.NoInspectionAvailable:
            pass
        else:
            cls.Coercer = pydantic.create_model(
                f'{cls.__name__}Coercer',
                __base__=_BaseCoercer,
                **{
                    c.name: (c.type.python_type, ...)
                    for c in inspector.columns
                    if not c.foreign_keys and not c.name.startswith('_') and not c.server_default
                },
            )


@as_declarative(constructor=None, metaclass=_BaseTableMeta)
class _BaseTable:
    Coercer: ClassVar[Type[_BaseCoercer]]
    metadata: ClassVar[MetaData]

    def __init__(self, **kwargs: Any) -> None:
        intermediate_obj = self.Coercer(**kwargs)
        for k, v in intermediate_obj:
            setattr(self, k, v)


ModelBase = _BaseTable


class Pkg(_BaseTable):
    __tablename__ = 'pkg'

    source = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    slug = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    url = Column(String, nullable=False)
    download_url = Column(String, nullable=False)
    date_published = Column(DateTime, nullable=False)
    version = Column(String, nullable=False)
    folders = cast(
        'List[PkgFolder]', relationship('PkgFolder', cascade='all, delete-orphan', backref='pkg')
    )
    options = cast(
        'PkgOptions', relationship('PkgOptions', cascade='all, delete-orphan', uselist=False)
    )
    deps = cast(
        'List[PkgDep]', relationship('PkgDep', cascade='all, delete-orphan', backref='pkg')
    )

    @property
    def logged_versions(self) -> List[PkgVersionLog]:
        session: Any = object_session(self)
        return (
            (
                session.query(PkgVersionLog)
                .filter(
                    and_(PkgVersionLog.pkg_source == self.source, PkgVersionLog.pkg_id == self.id)
                )
                .order_by(PkgVersionLog.install_time.desc())
                .all()
            )
            if session
            else []
        )


class PkgFolder(_BaseTable):
    __tablename__ = 'pkg_folder'
    __table_args__ = (ForeignKeyConstraint(['pkg_source', 'pkg_id'], ['pkg.source', 'pkg.id']),)

    name = Column(String, primary_key=True)
    pkg_source = Column(String, nullable=False)
    pkg_id = Column(String, nullable=False)


class PkgOptions(_BaseTable):
    __tablename__ = 'pkg_options'
    __table_args__ = (ForeignKeyConstraint(['pkg_source', 'pkg_id'], ['pkg.source', 'pkg.id']),)

    strategy = Column(String, nullable=False)
    pkg_source = Column(String, primary_key=True)
    pkg_id = Column(String, primary_key=True)


class PkgDep(_BaseTable):
    __tablename__ = 'pkg_dep'
    __table_args__ = (
        ForeignKeyConstraint(['pkg_source', 'pkg_id'], ['pkg.source', 'pkg.id']),
        UniqueConstraint('id', 'pkg_source', 'pkg_id', name='uq_id_per_foreign_key_constr'),
    )

    _id = Column(Integer, primary_key=True)
    id = Column(String, nullable=False)
    pkg_source = Column(String, nullable=False)
    pkg_id = Column(String, nullable=False)


class PkgVersionLog(_BaseTable):
    __tablename__ = 'pkg_version_log'

    version = Column(String, nullable=False, primary_key=True)
    install_time = Column(DateTime, nullable=False, server_default=func.now())
    pkg_source = Column(String, nullable=False, primary_key=True)
    pkg_id = Column(String, nullable=False, primary_key=True)


class _PkgFolder(_BaseCoercer):
    name: str


class _PkgOptions(_BaseCoercer):
    strategy: str


class _PkgDep(_BaseCoercer):
    id: str


class _PkgVersion(_BaseCoercer):
    version: str
    install_time: datetime


class PkgModel(_BaseCoercer):
    source: str
    id: str
    slug: str
    name: str
    description: str
    url: str
    download_url: str
    date_published: datetime
    version: str
    folders: List[_PkgFolder]
    options: _PkgOptions
    deps: List[_PkgDep]
    logged_versions: List[_PkgVersion]


class MultiPkgModel(pydantic.BaseModel):
    __root__: List[PkgModel]


def should_migrate(engine: Any, version: str) -> bool:
    """Check if the database version is the same as `version`;
    if not a migration would be required.
    """
    with engine.begin() as conn:
        try:
            current = conn.execute(
                'SELECT version_num FROM alembic_version WHERE version_num = (?)',
                version,
            ).scalar()
        except exc.OperationalError:
            return True
        else:
            return not current


def is_pkg(value: Any) -> bool:
    return isinstance(value, Pkg)
