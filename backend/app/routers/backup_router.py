"""Admin-only database backup/restore endpoints.

Supports both SQLite (via sqlite3 backup API) and PostgreSQL (via pg_dump / psql).
For PostgreSQL, pg_dump must be installed and accessible on the system PATH.
"""
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Response, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin, CurrentUser
from app.database import DATABASE_URL, _is_sqlite, _is_postgres

logger = logging.getLogger("trad_account.backup")

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"

# Retention policy for manual backups created via the API. Older manual
# backups beyond this count are auto-deleted when a new one is created.
# Auto-backups (auto_*) and pre-restore safety backups are excluded.
MANUAL_BACKUPS_KEEP = 10


def _resolve_db_path() -> str:
    """Resolve the SQLite database file path from DATABASE_URL.

    Handles both relative (sqlite:///./db) and absolute (sqlite:///C:/db) URLs.
    """
    parsed = urlparse(DATABASE_URL)
    db_path = parsed.path  # e.g. /C:/path/db or /./financial.db

    # On Windows, urlparse of sqlite:///C:/... gives path as /C:/...
    # Normalize: strip leading / for Windows absolute paths like /C:/ or /C:\
    if re.match(r'^/[A-Za-z]:[\\/]', db_path):
        db_path = db_path[1:]  # /C:/... → C:/...

    if os.path.isabs(db_path):
        return os.path.normpath(db_path)

    # Relative path: urlparse adds a leading / to sqlite:///./path (giving
    # "/./financial.db"). Strip it so os.path.join doesn't treat it as a
    # drive-root absolute path on Windows (which would resolve to D:\...
    # instead of <backend>/financial.db).
    if db_path.startswith('/'):
        db_path = db_path.lstrip('/')

    # Relative path: resolve from backend directory
    return os.path.normpath(os.path.join(os.path.dirname(BACKUP_DIR), db_path))


_PG_DUMP_CMD = os.environ.get("PG_DUMP_PATH", "pg_dump")
_PSQL_CMD = os.environ.get("PSQL_PATH", "psql")
_PG_RESTORE_CMD = os.environ.get("PG_RESTORE_PATH", "pg_restore")
_POSTGRES_CONTAINER = os.environ.get("POSTGRES_CONTAINER", "postgres")

# Docker container names allow [a-zA-Z0-9][a-zA-Z0-9_.-]*. We reject anything
# outside this set because _POSTGRES_CONTAINER is interpolated into a
# `wsl bash -c "docker exec ... <container> ..."` string; shell metacharacters
# in the env var would be a remote-code-execution vector. This guards both the
# restore path (line ~237) and the version-detection probes in _resolve_pg_tool.
_CONTAINER_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]*$')
if not _CONTAINER_NAME_RE.match(_POSTGRES_CONTAINER):
    raise RuntimeError(
        f"Invalid POSTGRES_CONTAINER value { _POSTGRES_CONTAINER!r}: "
        "must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ (Docker container name rules). "
        "Refusing to start with a value that could allow shell injection."
    )


def _resolve_pg_tool(tool: str, default_path: str) -> list[str]:
    """Resolve a PostgreSQL tool. Prefers Docker exec (version-matched), then PATH, then WSL."""
    # 1. Docker exec — always version-matched to the server
    try:
        subprocess.run(
            ["docker", "exec", _POSTGRES_CONTAINER, tool, "--version"],
            capture_output=True, check=True, timeout=10,
        )
        return ["docker", "exec", _POSTGRES_CONTAINER, tool]
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # 2. Docker exec via WSL (Windows dev with Docker Desktop / Docker in WSL2)
    if os.name == "nt":
        try:
            subprocess.run(
                ["wsl", "docker", "exec", _POSTGRES_CONTAINER, tool, "--version"],
                capture_output=True, check=True, timeout=10,
            )
            return ["wsl", "docker", "exec", _POSTGRES_CONTAINER, tool]
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    # 3. Direct PATH (production Dockerfile with postgresql-client installed)
    path = os.environ.get(f"PG_{tool.upper()}_PATH", "") or default_path
    try:
        subprocess.run([path, "--version"], capture_output=True, check=True, timeout=10)
        return [path]
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # 4. WSL fallback (Windows dev without Docker)
    if os.name == "nt":
        try:
            subprocess.run(["wsl", path, "--version"], capture_output=True, check=True, timeout=10)
            return ["wsl", path]
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    raise FileNotFoundError(
        f"{tool} not found — tried docker exec {_POSTGRES_CONTAINER} {tool}, "
        f"wsl docker exec {_POSTGRES_CONTAINER} {tool}, {path}, and wsl {path}. "
        f"Install postgresql-client or ensure the PostgreSQL container "
        f"'{_POSTGRES_CONTAINER}' is running."
    )


def _pg_creds():
    """Extract user, password, dbname from DATABASE_URL for Docker exec."""
    parsed = urlparse(DATABASE_URL)
    return parsed.username or "", parsed.password or "", (parsed.path or "").lstrip("/") or ""


def _pg_dump_check() -> str | None:
    """Verify pg_dump and related tools are available. Returns error or None."""
    missing = []
    for tool, default_path in [("pg_dump", _PG_DUMP_CMD), ("psql", _PSQL_CMD), ("pg_restore", _PG_RESTORE_CMD)]:
        try:
            _resolve_pg_tool(tool, default_path)
        except FileNotFoundError:
            missing.append(tool)
    if missing:
        return (
            f"PostgreSQL client tools not found: {', '.join(missing)}. "
            "Install postgresql-client (apt-get install postgresql-client) or ensure "
            f"the PostgreSQL container '{_POSTGRES_CONTAINER}' is running."
        )
    return None


def _pg_dump_to_file(output_path: str) -> None:
    """Run pg_dump and write a custom-format dump to the given file path.

    Prefers Docker exec (version-matched), then direct PATH, then WSL.
    """
    cmd = _resolve_pg_tool("pg_dump", _PG_DUMP_CMD)
    is_docker = "docker" in cmd  # covers both docker exec and wsl docker exec
    is_wsl = not is_docker and cmd[0] == "wsl"

    if is_docker:
        user, password, dbname = _pg_creds()
        env = os.environ.copy()
        env["PGPASSWORD"] = password
        with open(output_path, "wb") as f:
            subprocess.run(
                [*cmd, "-U", user, "-d", dbname,
                 "--format=c", "--compress=6", "--no-owner", "--no-privileges"],
                stdout=f, stderr=subprocess.PIPE, env=env,
                check=True, timeout=300,
            )
    elif is_wsl:
        with open(output_path, "wb") as f:
            subprocess.run(
                [*cmd, "--dbname", DATABASE_URL, "--format=c", "--compress=6",
                 "--no-owner", "--no-privileges"],
                stdout=f, stderr=subprocess.PIPE,
                check=True, timeout=300,
            )
    else:
        subprocess.run(
            [*cmd, "--dbname", DATABASE_URL, "--format=c", "--compress=6",
             "--no-owner", "--no-privileges", "--file", output_path],
            capture_output=True, check=True, timeout=300,
        )


def _pg_kill_connections(user: str, password: str, dbname: str) -> None:
    """Terminate all other connections to the database (best-effort)."""
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    # Validate dbname: only allow alphanumeric + underscore (defense in depth)
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_]+$', dbname):
        raise ValueError(f"Invalid database name: {dbname}")
    sql = (
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid()"
    )

    def _try(prefix: list[str]) -> None:
        try:
            subprocess.run(
                [*prefix, "psql", "-U", user, "-d", dbname, "-c", sql],
                capture_output=True, timeout=15, env=env,
            )
        except Exception:
            pass

    _try(["docker", "exec", _POSTGRES_CONTAINER])
    if os.name == "nt":
        _try(["wsl", "docker", "exec", _POSTGRES_CONTAINER])


def _pg_restore_from_file(pg_dump_path: str) -> None:
    """Restore PostgreSQL from a pg_dump custom-format file.

    Prefers Docker exec (version-matched), then direct PATH, then WSL.
    Disposes the SQLAlchemy engine before restore so --clean can drop tables.
    """

    # Release all web connections so pg_restore --clean can acquire table locks.
    # First dispose the pool (no new connections), then kill existing ones.
    from app.database import engine
    engine.dispose()
    _user, _password, _dbname = _pg_creds()
    _pg_kill_connections(_user, _password, _dbname)
    time.sleep(1)  # let server-side connection state settle

    cmd = _resolve_pg_tool("pg_restore", _PG_RESTORE_CMD)
    is_docker = "docker" in cmd  # covers both docker exec and wsl docker exec
    is_wsl = not is_docker and cmd[0] == "wsl"

    if is_docker:
        user, password, dbname = _pg_creds()
        env = os.environ.copy()
        env["PGPASSWORD"] = password

        # wsl docker exec: stdin piping through Python subprocess doesn't forward
        # reliably, so convert the path to WSL format and use bash redirection.
        if cmd[0] == "wsl":
            # Validate identifiers are safe (alphanumeric + underscore only)
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', user):
                raise HTTPException(status_code=400, detail="Invalid database user")
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', dbname):
                raise HTTPException(status_code=400, detail="Invalid database name")
            wsl_path = pg_dump_path.replace("\\", "/").replace("C:", "/mnt/c").replace("D:", "/mnt/d")
            password_quoted = shlex.quote(password)
            wsl_path_quoted = shlex.quote(wsl_path)
            user_quoted = shlex.quote(user)
            dbname_quoted = shlex.quote(dbname)
            proc = subprocess.run(
                ["wsl", "bash", "-c",
                 f"docker exec -i -e PGOPTIONS='-c statement_timeout=120000' "
                 f"-e PGPASSWORD={password_quoted} "
                 f"{_POSTGRES_CONTAINER} "
                 f"pg_restore -U {user_quoted} -d {dbname_quoted} --clean --if-exists "
                 f"--no-owner --no-privileges < {wsl_path_quoted}"],
                capture_output=True, env=env,
                timeout=300,
            )
        else:
            with open(pg_dump_path, "rb") as f:
                proc = subprocess.run(
                    [*cmd, "-U", user, "-d", dbname,
                     "--clean", "--if-exists", "--no-owner", "--no-privileges"],
                    stdin=f, capture_output=True, env=env,
                    timeout=300,
                )
        if proc.returncode != 0:
            stderr_text = proc.stderr.decode("utf-8", errors="replace")
            raise Exception(f"pg_restore failed (exit {proc.returncode}): {stderr_text}")
    elif is_wsl:
        with open(pg_dump_path, "rb") as f:
            proc = subprocess.run(
                [*cmd, "--dbname", DATABASE_URL, "--clean", "--if-exists",
                 "--no-owner", "--no-privileges"],
                stdin=f, capture_output=True,
                timeout=300,
            )
            if proc.returncode != 0:
                stderr_text = proc.stderr.decode("utf-8", errors="replace")
                raise Exception(f"pg_restore failed (exit {proc.returncode}): {stderr_text}")
    else:
        proc = subprocess.run(
            [*cmd, "--dbname", DATABASE_URL, "--clean", "--if-exists",
             "--no-owner", "--no-privileges", pg_dump_path],
            capture_output=True, timeout=300,
        )
        if proc.returncode != 0:
            stderr_text = proc.stderr.decode("utf-8", errors="replace")
            raise Exception(f"pg_restore failed (exit {proc.returncode}): {stderr_text}")

router = APIRouter()

# Only allow alphanumeric chars, underscores, and hyphens in backup IDs
_SAFE_BACKUP_ID = re.compile(r'^[a-zA-Z0-9_-]+$')


class BackupInfo(BaseModel):
    id: str
    filename: str
    size_bytes: int
    created_at: str
    db_checksum: str


class BackupList(BaseModel):
    backups: list[BackupInfo]


def _ensure_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _read_manifest(zip_path: Path) -> Optional[dict]:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open("manifest.json") as f:
                return json.loads(f.read())
    except Exception:
        return None


def _sanitize_backup_id(backup_id: str) -> str:
    if not _SAFE_BACKUP_ID.match(backup_id):
        raise HTTPException(status_code=400, detail="Invalid backup ID format")
    return backup_id


def _safe_extract(zf: zipfile.ZipFile, target_dir: str) -> None:
    """Extract zip entries safely, preventing path traversal (zip slip)."""
    for member in zf.namelist():
        member_path = os.path.normpath(os.path.join(target_dir, member))
        target_dir_real = os.path.realpath(target_dir)
        if not os.path.realpath(member_path).startswith(target_dir_real):
            raise HTTPException(status_code=400, detail="Invalid backup: path traversal detected")
    zf.extractall(target_dir)


def _db_checksum(db_path: str) -> str:
    sha = hashlib.sha256()
    with open(db_path, "rb") as f:
        while chunk := f.read(8192):
            sha.update(chunk)
    return sha.hexdigest()


def _scan_backups() -> list[BackupInfo]:
    _ensure_dir()
    results: list[BackupInfo] = []
    for f in sorted(BACKUP_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = f.stat()
        backup_id = f.stem
        manifest = _read_manifest(f)
        checksum = manifest.get("db_checksum", "") if manifest else ""
        results.append(BackupInfo(
            id=backup_id,
            filename=f.name,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            db_checksum=checksum,
        ))
    return results


@router.post("/backups", response_model=BackupInfo)
def create_backup(
    current_user: CurrentUser = Depends(require_admin),
):
    """Create a new backup (admin only). Archives database + uploads directory.

    Supports SQLite (via sqlite3 .backup API) and PostgreSQL (via pg_dump).
    For PostgreSQL, pg_dump must be installed and accessible on PATH.
    """
    _ensure_dir()

    timestamp = datetime.now(timezone.utc)
    backup_id = f"backup_{timestamp.strftime('%Y%m%d_%H%M%S')}"
    zip_path = BACKUP_DIR / f"{backup_id}.zip"
    db_checksum = ""

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if _is_sqlite:
            db_path = _resolve_db_path()
            if not os.path.exists(db_path):
                raise HTTPException(status_code=500, detail="Database file not found")

            src = None
            try:
                src = sqlite3.connect(db_path)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                    tmp_path = tmp.name
                try:
                    dst = sqlite3.connect(tmp_path)
                    src.backup(dst)
                    dst.close()
                    zf.write(tmp_path, "financial.db")
                    db_checksum = _db_checksum(tmp_path)
                finally:
                    os.unlink(tmp_path)
            except Exception:
                zf.write(db_path, "financial.db")
                db_checksum = _db_checksum(db_path)
            finally:
                if src is not None:
                    src.close()

            db_file = "financial.db"

        elif _is_postgres:
            pg_err = _pg_dump_check()
            if pg_err:
                raise HTTPException(status_code=500, detail=pg_err)

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".pgdump", delete=False) as tmp:
                    tmp_path = tmp.name
                _pg_dump_to_file(tmp_path)
                zf.write(tmp_path, "database.pgdump")
                db_checksum = _db_checksum(tmp_path)
            finally:
                if tmp_path is not None:
                    os.unlink(tmp_path)

            db_file = "database.pgdump"
        else:
            raise HTTPException(
                status_code=501,
                detail="Backup only supports SQLite and PostgreSQL databases.",
            )

        # Add uploads directory
        if UPLOADS_DIR.exists():
            for file_path in UPLOADS_DIR.rglob("*"):
                if file_path.is_file():
                    arcname = str(Path("uploads") / file_path.relative_to(UPLOADS_DIR))
                    zf.write(file_path, arcname)

        # Add manifest
        manifest = {
            "version": "2.0",
            "backup_id": backup_id,
            "created_at": timestamp.isoformat(),
            "db_checksum": db_checksum,
            "db_file": db_file,
            "db_engine": "postgresql" if _is_postgres else "sqlite",
            "sensitive_data_warning": "This backup contains hashed user credentials and financial data. Store securely and delete when no longer needed.",
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    size = zip_path.stat().st_size
    logger.info("Backup created: %s (%d bytes)", backup_id, size)

    # Auto-cleanup old manual backups. Keep only the most recent
    # MANUAL_BACKUPS_KEEP files with the "backup_" prefix. Auto-backups
    # (auto_*) are managed by auto_backup.py; pre_restore_* safety backups
    # are preserved as restore rollback points and never auto-deleted here.
    manual_files = sorted(
        BACKUP_DIR.glob("backup_*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in manual_files[MANUAL_BACKUPS_KEEP:]:
        try:
            old.unlink()
            logger.info("Auto-cleaned old manual backup: %s", old.name)
        except OSError as exc:
            logger.warning("Failed to clean old backup %s: %s", old.name, exc)

    return BackupInfo(
        id=backup_id,
        filename=zip_path.name,
        size_bytes=size,
        created_at=timestamp.isoformat(),
        db_checksum=db_checksum,
    )


@router.get("/backups", response_model=BackupList)
def list_backups(
    current_user: CurrentUser = Depends(require_admin),
):
    """List all available backups (admin only)."""
    return BackupList(backups=_scan_backups())


@router.get("/backups/{backup_id}/download")
def download_backup(
    backup_id: str,
    current_user: CurrentUser = Depends(require_admin),
):
    """Download a backup ZIP file (admin only)."""
    _sanitize_backup_id(backup_id)
    zip_path = BACKUP_DIR / f"{backup_id}.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    return StreamingResponse(
        zip_path.open("rb"),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{backup_id}.zip"'},
    )


@router.post("/backups/{backup_id}/restore")
def restore_backup(
    backup_id: str,
    x_confirm_restore: str = Header(..., alias="X-Confirm-Restore"),
    current_user: CurrentUser = Depends(require_admin),
):
    """Restore database from a backup (admin only, requires confirmation).

    WARNING: This replaces the current database and uploads directory.
    A pre-restore safety backup is created automatically.

    Supports SQLite and PostgreSQL databases.
    """
    _sanitize_backup_id(backup_id)
    zip_path = BACKUP_DIR / f"{backup_id}.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")

    if x_confirm_restore != "I understand this will overwrite all current data":
        raise HTTPException(
            status_code=400,
            detail="Must confirm restore by setting X-Confirm-Restore header to the exact confirmation message",
        )

    manifest = _read_manifest(zip_path)
    if not manifest:
        raise HTTPException(status_code=400, detail="Invalid backup: missing or corrupt manifest")

    db_engine = manifest.get("db_engine", "sqlite")
    db_file = manifest.get("db_file", "financial.db")
    if ".." in db_file or "/" in db_file or "\\" in db_file:
        raise HTTPException(status_code=400, detail="Invalid backup: db_file contains path traversal")

    # Create a pre-restore safety backup
    _ensure_dir()
    try:
        safety_id = f"pre_restore_{backup_id}_{int(time.time())}"
        safety_path = BACKUP_DIR / f"{safety_id}.zip"
        with zipfile.ZipFile(safety_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if _is_sqlite:
                db_path = _resolve_db_path()
                if os.path.exists(db_path):
                    zf.write(db_path, "financial.db")
            elif _is_postgres:
                # For PG, dump current state as safety backup
                with tempfile.NamedTemporaryFile(suffix=".pgdump", delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    _pg_dump_to_file(tmp_path)
                    zf.write(tmp_path, "database.pgdump")
                finally:
                    os.unlink(tmp_path)
            else:
                pass  # unknown engine, skip safety backup

            safe_manifest = {
                "version": "2.0",
                "backup_id": safety_id,
                "db_engine": db_engine,
                "safety_backup_for": backup_id,
                "sensitive_data_warning": "This backup contains hashed user credentials and financial data. Store securely and delete when no longer needed.",
            }
            zf.writestr("manifest.json", json.dumps(safe_manifest, indent=2))
        logger.info("Pre-restore safety backup created: %s", safety_id)
    except Exception as e:
        logger.error("Failed to create safety backup: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create safety backup, restore aborted")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if db_file not in zf.namelist():
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid backup: no database file '{db_file}' found",
                )

            with tempfile.TemporaryDirectory() as tmpdir:
                _safe_extract(zf, tmpdir)

                extracted_db = os.path.join(tmpdir, db_file)
                actual_checksum = _db_checksum(extracted_db)
                expected_checksum = manifest.get("db_checksum")

                if expected_checksum and actual_checksum != expected_checksum:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Backup integrity check failed. Expected: {expected_checksum[:16]}..., got: {actual_checksum[:16]}...",
                    )

                if db_engine == "postgresql":
                    pg_err = _pg_dump_check()
                    if pg_err:
                        raise HTTPException(status_code=500, detail=pg_err)
                    _pg_restore_from_file(extracted_db)
                elif db_engine == "sqlite":
                    db_path = _resolve_db_path()
                    shutil.copy2(extracted_db, db_path)
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Unknown database engine in backup: {db_engine}",
                    )

                # Restore uploads (atomic: rename old dir first, rollback on failure)
                extracted_uploads = os.path.join(tmpdir, "uploads")
                if os.path.isdir(extracted_uploads):
                    _old_uploads = None
                    if UPLOADS_DIR.exists():
                        _old_uploads = UPLOADS_DIR.with_suffix('.bak.' + str(int(time.time())))
                        UPLOADS_DIR.rename(_old_uploads)
                    try:
                        shutil.copytree(extracted_uploads, UPLOADS_DIR)
                        # Remove old uploads dir only after successful copy
                        if _old_uploads and _old_uploads.exists():
                            shutil.rmtree(_old_uploads)
                    except Exception:
                        # Rollback: restore old uploads
                        if _old_uploads and _old_uploads.exists():
                            if UPLOADS_DIR.exists():
                                shutil.rmtree(UPLOADS_DIR)
                            _old_uploads.rename(UPLOADS_DIR)
                        raise

        logger.warning("Restore completed from backup: %s (by %s)", backup_id, current_user.username)
        return {"status": "success", "message": f"Restored from {backup_id}", "safety_backup": safety_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Restore failed: %s", e)
        raise HTTPException(status_code=500, detail="Restore failed due to an internal error")


@router.delete("/backups/{backup_id}")
def delete_backup(
    backup_id: str,
    current_user: CurrentUser = Depends(require_admin),
):
    """Delete a backup file (admin only)."""
    _sanitize_backup_id(backup_id)
    zip_path = BACKUP_DIR / f"{backup_id}.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    zip_path.unlink()
    logger.info("Backup deleted: %s (by %s)", backup_id, current_user.username)
    return {"status": "success", "message": f"Backup {backup_id} deleted"}


@router.post("/backups/upload")
def upload_backup(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_admin),
):
    """Upload a backup ZIP file from another system (admin only)."""
    _ensure_dir()
    # Sanitize filename
    safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', file.filename or "uploaded_backup.zip")
    backup_id = safe_name.replace(".zip", "")
    dest_path = BACKUP_DIR / f"{backup_id}.zip"

    # Verify it's a valid zip with manifest
    content = file.file.read()
    file.file.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        with zipfile.ZipFile(tmp_path, "r") as zf:
            if "manifest.json" not in zf.namelist():
                raise HTTPException(status_code=400, detail="Invalid backup: no manifest.json found")
        shutil.move(tmp_path, str(dest_path))
    except HTTPException:
        os.unlink(tmp_path)
        raise
    except Exception:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail="Invalid backup: not a valid ZIP file")

    stat = dest_path.stat()
    manifest = _read_manifest(dest_path)
    checksum = manifest.get("db_checksum", "") if manifest else ""
    logger.info("Backup uploaded: %s (%d bytes, by %s)", backup_id, stat.st_size, current_user.username)
    return BackupInfo(
        id=backup_id,
        filename=dest_path.name,
        size_bytes=stat.st_size,
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        db_checksum=checksum,
    )
