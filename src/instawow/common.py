from __future__ import annotations

from .utils import StrEnum


class Strategy(StrEnum):
    default = 'default'
    latest = 'latest'
    any_flavour = 'any_flavour'
    version = 'version'
