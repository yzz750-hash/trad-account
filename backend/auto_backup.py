"""Bi-weekly auto-backup script. Runs from Windows Task Scheduler or cron.

Even if the scheduler invokes this script daily, it throttles to one real
backup every 14 days by checking the mtime of the most recent auto_*.zip.
Keeps the last 4 auto-backups (≈ 2 months of history).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Load .env before importing app modules so JWT_SECRET_KEY and DATABASE_URL
# are available when running as a standalone script (uvicorn loads .env
# automatically, but `python auto_backup.py` does not).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass
from app.routers.backup_router import _ensure_dir, _resolve_db_path, _db_checksum, _is_sqlite, _is_postgres, BACKUP_DIR, UPLOADS_DIR, _pg_dump_check, _pg_dump_to_file
from datetime import datetime, timezone, timedelta
import zipfile, json, os, tempfile, sqlite3, shutil
from pathlib import Path

# --- Throttle: skip if the latest auto-backup is less than 14 days old ---
_ensure_dir()
_auto_files = sorted(BACKUP_DIR.glob("auto_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
BACKUP_INTERVAL_DAYS = 14
if _auto_files:
    _latest_mtime = _auto_files[0].stat().st_mtime
    _days_since = (datetime.now(timezone.utc).timestamp() - _latest_mtime) / 86400.0
    if _days_since < BACKUP_INTERVAL_DAYS:
        _next_in = BACKUP_INTERVAL_DAYS - _days_since
        print(f"SKIP: last auto-backup was {_days_since:.1f} days ago (threshold {BACKUP_INTERVAL_DAYS}). "
              f"Next backup in {_next_in:.1f} days. Existing auto-backups: {len(_auto_files)}.")
        sys.exit(0)

timestamp = datetime.now(timezone.utc)
backup_id = f"auto_{timestamp.strftime('%Y%m%d_%H%M%S')}"
zip_path = BACKUP_DIR / f"{backup_id}.zip"

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    if _is_sqlite:
        db_path = _resolve_db_path()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            tmp_path = tmp.name
        try:
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(tmp_path)
            src.backup(dst)
            dst.close()
            src.close()
            zf.write(tmp_path, "financial.db")
            db_checksum = _db_checksum(tmp_path)
        finally:
            os.unlink(tmp_path)
        db_file = "financial.db"

    elif _is_postgres:
        with tempfile.NamedTemporaryFile(suffix=".pgdump", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            _pg_dump_to_file(tmp_path)
            zf.write(tmp_path, "database.pgdump")
            db_checksum = _db_checksum(tmp_path)
        finally:
            os.unlink(tmp_path)
        db_file = "database.pgdump"
    else:
        raise RuntimeError("Unsupported database engine")

    if UPLOADS_DIR.exists():
        for file_path in UPLOADS_DIR.rglob("*"):
            if file_path.is_file():
                arcname = str(Path("uploads") / file_path.relative_to(UPLOADS_DIR))
                zf.write(file_path, arcname)

    manifest = {
        "version": "2.0", "backup_id": backup_id,
        "created_at": timestamp.isoformat(), "db_checksum": db_checksum,
        "db_file": db_file, "db_engine": "postgresql" if _is_postgres else "sqlite",
        "auto": True,
    }
    zf.writestr("manifest.json", json.dumps(manifest, indent=2))

size_kb = zip_path.stat().st_size / 1024

# Keep only last 4 bi-weekly auto-backups (≈ 2 months of history)
auto_files = sorted(BACKUP_DIR.glob("auto_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
for old in auto_files[4:]:
    old.unlink()

print(f"OK: {backup_id}.zip ({size_kb:.0f} KB), kept {min(len(auto_files), 4)} auto backups")
