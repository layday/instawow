# pyright: reportUnusedImport=false

from alembic.command import (branches, current, downgrade, edit, heads, history, init,
                             list_templates, merge, revision, show, stamp, upgrade)
from alembic.config import Config as AlembicConfig


def make_config(url: str) -> AlembicConfig:
    config = AlembicConfig()
    config.set_main_option('script_location', 'instawow:migrations')
    config.set_main_option('sqlalchemy.url', url)
    return config
