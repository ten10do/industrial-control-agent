import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from backend.database_schema import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = os.getenv("DATABASE_URL", "").strip()
if database_url.startswith("postgres://"):
    database_url = f"postgresql+psycopg://{database_url.removeprefix('postgres://')}"
elif database_url.startswith("postgresql://"):
    database_url = (
        f"postgresql+psycopg://{database_url.removeprefix('postgresql://')}"
    )
if database_url:
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() == "postgresql" and "sslmode" not in parsed_url.query:
        parsed_url = parsed_url.update_query_dict(
            {"sslmode": os.getenv("DATABASE_SSLMODE", "require")},
        )
    config.set_main_option(
        "sqlalchemy.url",
        parsed_url.render_as_string(hide_password=False).replace("%", "%%"),
    )

target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
