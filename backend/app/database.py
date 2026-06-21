import os
import logging
from sqlalchemy import create_engine, event, pool
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("trad_account")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///./financial.db",
)

_is_postgres = DATABASE_URL.startswith("postgresql://") or DATABASE_URL.startswith("postgres://")
_is_sqlite = DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    if os.environ.get("ENVIRONMENT") == "production":
        raise RuntimeError(
            "SQLite is not supported in production mode. "
            "SQLite lacks row-level locking (SELECT ... FOR UPDATE), which is required for "
            "concurrent voucher numbering, reconciliation, and period closing to be correct. "
            "Set DATABASE_URL=postgresql://user:pass@host:5432/dbname to use PostgreSQL."
        )
    connect_args: dict = {"check_same_thread": False}
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        poolclass=pool.QueuePool,
        pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT", "30")),
    )

    @event.listens_for(engine, "connect")
    def _sqlite_on_connect(dbapi_connection, connection_record):
        """Enable WAL mode and set busy timeout for concurrent access."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        finally:
            cursor.close()

elif _is_postgres:
    # PostgreSQL: production-grade with connection pooling
    pool_size = int(os.environ.get("DB_POOL_SIZE", "20"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
    pool_timeout = int(os.environ.get("DB_POOL_TIMEOUT", "30"))

    engine = create_engine(
        DATABASE_URL,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,  # verify connections before use (detects stale connections)
        pool_recycle=3600,   # recycle connections hourly to avoid pg server-side timeouts
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, connection_record):
        """Set application_name for PostgreSQL query identification."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET application_name = 'trad_account'")
        except Exception:
            pass
        finally:
            cursor.close()

    logger.info("PostgreSQL engine configured: pool_size=%d max_overflow=%d", pool_size, max_overflow)

else:
    # Unknown database URL — attempt with defaults
    engine = create_engine(DATABASE_URL)
    logger.info("Database engine configured for: %s", DATABASE_URL.split("://")[0])

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
