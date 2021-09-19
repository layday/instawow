from datetime import datetime

import click

from instawow.common import Strategy
from instawow.models import Pkg
import instawow.plugins
from instawow.resolvers import BaseResolver, ChangelogFormat, Defn


@click.command()
def foo():
    "don't foo where you bar"
    print('success!')


class MyResolver(BaseResolver):
    source = 'me'
    name = "It's me"
    strategies = frozenset({Strategy.default})
    changelog_format = ChangelogFormat.markdown

    async def resolve_one(self, defn: Defn, metadata: None) -> Pkg:
        return Pkg(
            source=self.source,
            id='bar',
            slug='bar',
            name='Bar',
            description='The quintessential bar add-on, brought to you by yours truly',
            url='http://example.com/',
            download_url='file:///...',
            date_published=datetime.now(),
            version='0',
            changelog_url='data:,',
            options={'strategy': defn.strategy},
        )


@instawow.plugins.hookimpl
def instawow_add_commands():
    return (foo,)


@instawow.plugins.hookimpl
def instawow_add_resolvers():
    return (MyResolver,)
