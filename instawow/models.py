from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional as O, Type

import pydantic
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    String,
    TypeDecorator,
    and_,
    exc,
    func,
    inspect,
)
from sqlalchemy.ext.declarative import DeclarativeMeta, declarative_base
from sqlalchemy.orm import Session, object_session, relationship


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


_coercers: Dict[type, Type[pydantic.BaseModel]] = {}


class _ModelMeta(DeclarativeMeta):
    def __init__(cls, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        inspector = inspect(cls, raiseerr=False)
        if inspector:
            _coercers[cls] = pydantic.create_model(
                f'{cls.__name__}Coercer',
                __base__=_BaseCoercer,
                **{
                    c.name: (c.type.python_type, ...)
                    for c in inspector.columns
                    if not c.foreign_keys and not c.name.startswith('_') and not c.server_default
                },
            )


def _constructor(self: object, **kwargs: Any) -> None:
    intermediate_obj = _coercers[self.__class__](**kwargs)
    for k, v in intermediate_obj:
        setattr(self, k, v)


ModelBase: Any = declarative_base(constructor=_constructor, metaclass=_ModelMeta)

if TYPE_CHECKING:
    TZDateTime_base_class = TypeDecorator[datetime]
else:
    TZDateTime_base_class = TypeDecorator


class TZDateTime(TZDateTime_base_class):
    impl = DateTime

    def process_bind_param(self, value: O[datetime], dialect: Any) -> O[datetime]:  # type: ignore
        if value is not None:
            if not value.tzinfo:
                raise TypeError('tzinfo is required')
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: O[datetime], dialect: Any) -> O[datetime]:
        return value and value.replace(tzinfo=timezone.utc)

    @property
    def python_type(self):
        return datetime


class Pkg(ModelBase):
    __tablename__ = 'pkg'

    source = Column(String, primary_key=True)
    id = Column(String, primary_key=True)
    slug = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=False)
    url = Column(String, nullable=False)
    download_url = Column(String, nullable=False)
    date_published = Column(TZDateTime, nullable=False)
    version = Column(String, nullable=False)
    folders: relationship[List[PkgFolder]] = relationship(
        'PkgFolder', cascade='all, delete-orphan', backref='pkg'
    )
    options: relationship[PkgOptions] = relationship(
        'PkgOptions', cascade='all, delete-orphan', uselist=False
    )
    deps: relationship[List[PkgDep]] = relationship(
        'PkgDep', cascade='all, delete-orphan', backref='pkg'
    )

    @property
    def logged_versions(self) -> List[PkgVersionLog]:
        session: O[Session] = object_session(self)
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


class PkgFolder(ModelBase):
    __tablename__ = 'pkg_folder'
    __table_args__ = (ForeignKeyConstraint(['pkg_source', 'pkg_id'], ['pkg.source', 'pkg.id']),)

    name = Column(String, primary_key=True)
    pkg_source = Column(String, nullable=False)
    pkg_id = Column(String, nullable=False)


class PkgOptions(ModelBase):
    __tablename__ = 'pkg_options'
    __table_args__ = (ForeignKeyConstraint(['pkg_source', 'pkg_id'], ['pkg.source', 'pkg.id']),)

    strategy = Column(String, nullable=False)
    pkg_source = Column(String, primary_key=True)
    pkg_id = Column(String, primary_key=True)


class PkgDep(ModelBase):
    __tablename__ = 'pkg_dep'
    __table_args__ = (ForeignKeyConstraint(['pkg_source', 'pkg_id'], ['pkg.source', 'pkg.id']),)

    id = Column(String, primary_key=True)
    pkg_source = Column(String, primary_key=True)
    pkg_id = Column(String, primary_key=True)


class PkgVersionLog(ModelBase):
    __tablename__ = 'pkg_version_log'

    version = Column(String, primary_key=True)
    install_time = Column(TZDateTime, nullable=False, server_default=func.now())
    pkg_source = Column(String, primary_key=True)
    pkg_id = Column(String, primary_key=True)


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
