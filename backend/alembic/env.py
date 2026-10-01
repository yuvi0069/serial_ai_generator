"""Alembic environment. Connects with the app's own engine (DATABASE_URL from .env, pooler-safe
settings) and diffs against the ORM models. LangGraph's checkpoint tables are owned by
PostgresSaver.setup(), so they are excluded from autogenerate."""
from logging.config import fileConfig

from alembic import context

from app.db import IS_SQLITE, engine, normalize_db_url
from app.config import settings
from app.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
EXTERNAL_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}


def include_object(obj, name, type_, reflected, compare_to):
    """Skip tables we don't own (LangGraph checkpointer) so autogenerate never drops them."""
    return not (type_ == "table" and name in EXTERNAL_TABLES)


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: emit SQL without connecting."""
    context.configure(url=normalize_db_url(settings.database_url), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"},
                      include_object=include_object, render_as_batch=IS_SQLITE)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          include_object=include_object, render_as_batch=IS_SQLITE, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
