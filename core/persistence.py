import logging
import os
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone as utc_timezone
from pathlib import Path

from django.conf import settings
from django.db import connections

logger = logging.getLogger("core.persistence")
_backup_lock = threading.Lock()
_state_lock = threading.Lock()
_last_error = ""
_last_success = ""


def state():
    with _state_lock:
        return {"error": _last_error, "last_success": _last_success}


def backup_database():
    """Create a consistent SQLite backup and atomically publish it to the persistent volume."""
    global _last_error, _last_success
    with _backup_lock:
        destination = Path(settings.PERSISTENCE_DIR) / "backups"
        destination.mkdir(parents=True, exist_ok=True)
        temporary_name = None
        try:
            handle = tempfile.NamedTemporaryFile(prefix="sqlite-", suffix=".tmp", dir=destination, delete=False)
            temporary_name = handle.name
            handle.close()
            source = connections["default"]
            source.ensure_connection()
            target = sqlite3.connect(temporary_name, timeout=30)
            try:
                source.connection.backup(target, pages=256, sleep=0.05)
                result = target.execute("PRAGMA integrity_check").fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError("integrity_check did not return ok")
                target.commit()
            finally:
                target.close()
            latest = destination / "latest.sqlite3"
            os.replace(temporary_name, latest)
            temporary_name = None
            day = datetime.now(utc_timezone.utc).strftime("%Y-%m-%d")
            daily = destination / f"daily-{day}.sqlite3"
            if not daily.exists():
                shutil.copyfile(latest, daily)
            for old in destination.glob("daily-*.sqlite3"):
                if (datetime.now(utc_timezone.utc).date() - datetime.strptime(old.stem.removeprefix("daily-"), "%Y-%m-%d").date()).days > 14:
                    old.unlink(missing_ok=True)
            marker_tmp = Path(settings.PERSISTENCE_DIR) / ".safetyinspection-initialized.tmp"
            marker = Path(settings.PERSISTENCE_DIR) / ".safetyinspection-initialized"
            marker_tmp.write_text(datetime.now(utc_timezone.utc).isoformat(), encoding="utf-8")
            os.replace(marker_tmp, marker)
            with _state_lock:
                _last_error = ""
                _last_success = datetime.now(utc_timezone.utc).isoformat()
        except Exception as exc:
            with _state_lock:
                _last_error = str(exc)[:300]
            logger.exception("SQLite snapshot could not be saved to persistent storage")
            raise
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)


def restore_database():
    """Restore only from a verified SQLite snapshot; fail closed if a previous install is missing it."""
    source = Path(settings.PERSISTENCE_DIR) / "backups" / "latest.sqlite3"
    marker = Path(settings.PERSISTENCE_DIR) / ".safetyinspection-initialized"
    target = Path(settings.DATABASES["default"]["NAME"])
    if not source.exists():
        if marker.exists():
            raise RuntimeError("The app has existing persistent data, but its SQLite snapshot is missing. Refusing to create an empty database.")
        logger.info("No earlier snapshot exists; initializing a new database.")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    check = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError("The persistent SQLite snapshot failed its integrity check.")
    finally:
        check.close()
    tmp = target.with_suffix(target.suffix + ".restore-tmp")
    if tmp.exists(): tmp.unlink()
    source_db = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=30)
    target_db = sqlite3.connect(str(tmp), timeout=30)
    try:
        source_db.backup(target_db)
        result = target_db.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok": raise RuntimeError("Restored database integrity check failed.")
        target_db.commit()
    finally:
        target_db.close(); source_db.close()
    os.replace(tmp, target)
    return True
