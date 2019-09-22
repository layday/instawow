from alembic.command import (list_templates, init, revision, merge, upgrade,
                             downgrade, show, history, heads, branches, current,
                             stamp, edit)
from alembic.config import Config as AlembicConfig


def make_config(url: str) -> AlembicConfig:
    config = AlembicConfig()
    config.set_main_option('script_location', 'instawow:migrations')
    config.set_main_option('sqlalchemy.url', url)
    return config
