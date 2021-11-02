from __future__ import annotations

from .utils import StrEnum


class Strategy(StrEnum):
    default = 'default'
    latest = 'latest'
    curse_latest_beta = 'curse_latest_beta'
    curse_latest_alpha = 'curse_latest_alpha'
    any_flavour = 'any_flavour'
    version = 'version'
