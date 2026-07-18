import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv
from app.database import Base

# Load .env so alembic CLI picks up DATABASE_URL/JWT_SECRET_KEY/etc.
# main.py loads the same file via load_dotenv(override=True); we mirror that
# here so `alembic upgrade head` works identically to app startup.
# NOTE: override=False so tests that set DATABASE_URL=sqlite://... are not
# clobbered by the .env file's production DATABASE_URL. In production, the
# deployment environment should set DATABASE_URL directly (docker-compose,
# systemd, etc.) rather than relying on .env to override system env.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BACKEND_ROOT, ".env"), override=False)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Read DATABASE_URL at runtime so tests can override the env var (module-level
# imports are frozen after first import; env vars are always current).
_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./financial.db")
config.set_main_option("sqlalchemy.url", _DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
