from __future__ import annotations

from .cfcore import CfCoreResolver
from .github import GithubResolver
from .instawow import InstawowResolver
from .tukui import TukuiResolver
from .wago import WagoResolver
from .wowi import WowiResolver

DEFAULT_RESOLVERS = [
    GithubResolver,
    CfCoreResolver,
    WowiResolver,
    TukuiResolver,
    InstawowResolver,
    WagoResolver,
]
