from __future__ import annotations

from .utils import StrEnum


class Flavour(StrEnum):
    # The latest Classic version is always aliased to "classic".
    # The logic here is that should Classic not be discontinued
    # it will continue to be updated in place so that new Classic versions
    # will inherit the "_classic_" folder.  This means we won't have to
    # migrate Classic profiles either automatically or by requiring user
    # intervention for new Classic releases.
    retail = 'retail'
    vanilla_classic = 'vanilla_classic'
    burning_crusade_classic = 'classic'


class Strategy(StrEnum):
    default = 'default'
    latest = 'latest'
    any_flavour = 'any_flavour'
    version = 'version'


class ChangelogFormat(StrEnum):
    html = 'html'
    markdown = 'markdown'
    bbcode = 'bbcode'
    raw = 'raw'
