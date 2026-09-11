from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registra le tabelle nel metadata)
from app.config import settings
from app.db import Base, make_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
# render_as_batch: SQLite non supporta ALTER TABLE completo, Alembic ricrea la tabella.
options = {"target_metadata": target_metadata, "render_as_batch": True, "compare_type": True}


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, literal_binds=True, dialect_opts={"paramstyle": "named"}, **options)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with make_engine(settings.database_url).connect() as connection:
        context.configure(connection=connection, **options)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
