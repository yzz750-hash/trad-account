"""Tests for Alembic migration chain: upgrade head / downgrade base / round-trip.

These tests use their own temporary databases and do NOT depend on conftest fixtures.
"""
import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BACKEND_DIR / "alembic"


def _create_alembic_config(db_url: str) -> Config:
    ini_path = BACKEND_DIR / "alembic.ini"
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


EXPECTED_TABLES = {
    "account_balances", "accounts", "accounting_periods", "audit_logs",
    "business_partners", "closing_operations", "commission_rules", "currencies",
    "exchange_rates", "fixed_assets", "ledgers", "oem_contracts", "open_items",
    "original_documents", "reconciliation_records", "salespersons",
    "tax_rates", "users", "vat_records", "voucher_entries",
    "voucher_number_counters", "vouchers",
}


def _clean_db_file(path: Path):
    """Delete a SQLite DB file, retrying if locked (Windows WAL)."""
    import time
    if not path.exists():
        return
    for _ in range(5):
        try:
            path.unlink()
            return
        except PermissionError:
            time.sleep(0.5)
    # Last resort: try deleting -wal and -shm files instead
    try:
        for ext in ('', '-wal', '-shm'):
            p = path.with_suffix(path.suffix + ext) if ext else path
            if p.exists():
                p.unlink()
    except Exception:
        pass

class TestModelDrift:
    """Verify no drift between ORM models and migration-generated schema."""

    def test_no_model_drift(self):
        db_path = BACKEND_DIR / "tests" / "_alembic_drift.db"
        _clean_db_file(db_path)
        db_url = f"sqlite:///{db_path}"

        _saved_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = db_url
            config = _create_alembic_config(db_url)
            # Upgrade to head
            command.upgrade(config, "head")

            # Now create tables from ORM models and compare
            from app.database import Base
            from sqlalchemy import MetaData

            orm_engine = create_engine(db_url, connect_args={"check_same_thread": False})
            try:
                # Get migration schema
                mig_inspector = inspect(orm_engine)
                mig_tables = mig_inspector.get_table_names()
                mig_schema = {}
                for t in sorted(mig_tables):
                    cols = {c['name']: c['type'] for c in mig_inspector.get_columns(t)}
                    mig_schema[t] = cols

                # Get ORM schema by creating all tables in a separate temp DB
                drift_path = BACKEND_DIR / "tests" / "_alembic_drift_orm.db"
                _clean_db_file(drift_path)
                orm_url = f"sqlite:///{drift_path}"
                orm_engine2 = create_engine(orm_url, connect_args={"check_same_thread": False})
                Base.metadata.create_all(bind=orm_engine2)

                orm_inspector = inspect(orm_engine2)
                orm_tables = set(orm_inspector.get_table_names())

                # Migration should have all ORM tables
                missing = orm_tables - set(mig_tables)
                extra = set(mig_tables) - orm_tables - {"alembic_version"}
                assert not missing, f"ORM tables missing from migration: {missing}"
                assert not extra, f"Migration has extra tables not in ORM: {extra}"
                print(f"Drift check OK: {len(orm_tables)} tables match")
            finally:
                orm_engine.dispose()
        finally:
            if _saved_url is not None:
                os.environ["DATABASE_URL"] = _saved_url
            _clean_db_file(db_path)
            _clean_db_file(BACKEND_DIR / "tests" / "_alembic_drift_orm.db")



class TestAlembicUpgradeHead:

    def test_upgrade_head_creates_all_tables(self):
        db_path = BACKEND_DIR / "tests" / "_alembic_upgrade.db"
        _clean_db_file(db_path)
        db_url = f"sqlite:///{db_path}"

        _saved_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = db_url
            config = _create_alembic_config(db_url)
            command.upgrade(config, "head")

            engine = create_engine(db_url, connect_args={"check_same_thread": False})
            try:
                inspector = inspect(engine)
                tables = set(inspector.get_table_names())
                # alembic_version is the migration tracking table, not an app model
                tables.discard("alembic_version")
                missing = EXPECTED_TABLES - tables
                extra = tables - EXPECTED_TABLES
                assert not missing, f"Missing tables: {missing}"
                assert not extra, f"Unexpected tables: {extra}"

                with engine.connect() as conn:
                    rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                    assert rev == "d1e2f3a4b5c6", f"Expected head d1e2f3a4b5c6, got {rev}"
            finally:
                engine.dispose()
        finally:
            if _saved_url is not None:
                os.environ["DATABASE_URL"] = _saved_url
            _clean_db_file(db_path)

    def test_downgrade_base_removes_all(self):
        db_path = BACKEND_DIR / "tests" / "_alembic_downgrade.db"
        _clean_db_file(db_path)
        db_url = f"sqlite:///{db_path}"

        _saved_url = os.environ.get("DATABASE_URL")
        try:
            os.environ["DATABASE_URL"] = db_url
            config = _create_alembic_config(db_url)
            command.upgrade(config, "head")
            command.downgrade(config, "base")

            engine = create_engine(db_url, connect_args={"check_same_thread": False})
            try:
                inspector = inspect(engine)
                tables = set(inspector.get_table_names())
                app_tables = tables - {"alembic_version"}
                assert not app_tables, f"Tables should be empty after downgrade, got: {app_tables}"
            finally:
                engine.dispose()
        finally:
            if _saved_url is not None:
                os.environ["DATABASE_URL"] = _saved_url
            _clean_db_file(db_path)

    def test_revision_chain_has_no_gaps(self):
        """Verify migration linear chain from initial to head."""
        from alembic.script import ScriptDirectory
        config = _create_alembic_config("sqlite://")
        config.set_main_option("script_location", str(MIGRATIONS_DIR))
        script = ScriptDirectory.from_config(config)

        revs = list(script.walk_revisions())
        assert len(revs) == 15, f"Expected 15 revisions, got {len(revs)}"
        head = script.get_revision("head")
        assert head.revision == "d1e2f3a4b5c6"

    def test_all_revisions_have_downgrade(self):
        versions_dir = MIGRATIONS_DIR / "versions"
        for py_file in sorted(versions_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            content = py_file.read_text(encoding="utf-8")
            assert "def upgrade()" in content, f"{py_file.name}: missing upgrade()"
            assert "def downgrade()" in content, f"{py_file.name}: missing downgrade()"
