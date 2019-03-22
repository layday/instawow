
from alembic import context
from sqlalchemy import engine_from_config, pool

from instawow.models import ModelBase


target_metadata = ModelBase.metadata


def run_offline() -> None:
    url = context.config.get_main_option('sqlalchemy.url')
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    alembic_config = context.config.get_section(context.config.config_ini_section)
    engine = engine_from_config(alembic_config,
                                prefix='sqlalchemy.',
                                poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection,
                          target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


def main() -> None:
    if context.is_offline_mode():
        run_offline()
    else:
        run_online()


if __name__ == 'env_py':    # Alembic appears to mangle the module's `__name__`
    main()
