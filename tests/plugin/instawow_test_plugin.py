from datetime import datetime

import click

from instawow.models import Pkg, PkgOptions
import instawow.plugins
from instawow.resolvers import Defn, Resolver, Strategy


@click.command()
def foo():
    "don't foo where you bar"
    print('success!')


class MyResolver(Resolver):
    source = 'me'
    name = "It's me"
    strategies = frozenset({Strategy.default})

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
            options=PkgOptions(strategy=defn.strategy),
        )


@instawow.plugins.hookimpl
def instawow_add_commands():
    return (foo,)


@instawow.plugins.hookimpl
def instawow_add_resolvers():
    return (MyResolver,)
