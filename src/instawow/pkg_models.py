from __future__ import annotations

from datetime import datetime

from attrs import asdict, field, frozen
from typing_extensions import Self

from .common import Defn, StrategyValues


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
    folders: list[PkgFolder] = field(factory=list)  # pkg_folder
    deps: list[PkgDep] = field(factory=list)  # pkg_dep
    logged_versions: list[PkgLoggedVersion] = field(factory=list)  # pkg_version_log

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
