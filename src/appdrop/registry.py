"""SQLite-backed registry for installed applications.

Stores metadata about every AppImage and Debian package managed by AppDrop,
including version history for rollback support.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from appdrop.config import registry_path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS apps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    display_name    TEXT,
    format          TEXT    NOT NULL CHECK (format IN ('appimage', 'deb')),
    version         TEXT,
    architecture    TEXT,
    description     TEXT,
    install_path    TEXT,
    desktop_entry   TEXT,
    icon_path       TEXT,
    installed_at    TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'installed'
                    CHECK (status IN ('installed', 'removed', 'failed')),
    metadata_json   TEXT,
    UNIQUE(name, format)
);

CREATE TABLE IF NOT EXISTS version_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id          INTEGER NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
    version         TEXT,
    backup_path     TEXT,
    action          TEXT    NOT NULL CHECK (action IN ('install', 'update', 'rollback', 'uninstall')),
    created_at      TEXT    NOT NULL,
    notes           TEXT
);
"""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AppRecord:
    """A row from the ``apps`` table."""

    id: int | None = None
    name: str = ""
    display_name: str | None = None
    format: str = ""  # "appimage" or "deb"
    version: str | None = None
    architecture: str | None = None
    description: str | None = None
    install_path: str | None = None
    desktop_entry: str | None = None
    icon_path: str | None = None
    installed_at: str = ""
    updated_at: str = ""
    status: str = "installed"
    metadata_json: str | None = None


@dataclass
class VersionRecord:
    """A row from the ``version_history`` table."""

    id: int | None = None
    app_id: int = 0
    version: str | None = None
    backup_path: str | None = None
    action: str = ""
    created_at: str = ""
    notes: str | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class Registry:
    """Persistent application registry backed by SQLite."""

    def __init__(self, *, root_override: Path | None = None) -> None:
        self._db_path = registry_path(root_override)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open (or create) the database and apply migrations."""
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Registry is not open — call .open() first")
        return self._conn

    def _ensure_schema(self) -> None:
        cur = self._db.executescript(_SCHEMA_SQL)
        # Insert schema version if empty
        row = self._db.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._db.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (_SCHEMA_VERSION,),
            )
            self._db.commit()

    # ------------------------------------------------------------------
    # App CRUD
    # ------------------------------------------------------------------

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def add_app(self, rec: AppRecord) -> int:
        """Insert a new app record. Returns the new row id."""
        now = self._now()
        rec.installed_at = now
        rec.updated_at = now
        cur = self._db.execute(
            """INSERT INTO apps
               (name, display_name, format, version, architecture,
                description, install_path, desktop_entry, icon_path,
                installed_at, updated_at, status, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.name, rec.display_name, rec.format, rec.version,
                rec.architecture, rec.description, rec.install_path,
                rec.desktop_entry, rec.icon_path,
                rec.installed_at, rec.updated_at, rec.status,
                rec.metadata_json,
            ),
        )
        self._db.commit()
        rec.id = cur.lastrowid
        return rec.id  # type: ignore[return-value]

    def update_app(self, rec: AppRecord) -> None:
        """Update an existing app record (matched by id)."""
        rec.updated_at = self._now()
        self._db.execute(
            """UPDATE apps SET
               name=?, display_name=?, format=?, version=?, architecture=?,
               description=?, install_path=?, desktop_entry=?, icon_path=?,
               updated_at=?, status=?, metadata_json=?
               WHERE id=?""",
            (
                rec.name, rec.display_name, rec.format, rec.version,
                rec.architecture, rec.description, rec.install_path,
                rec.desktop_entry, rec.icon_path,
                rec.updated_at, rec.status, rec.metadata_json,
                rec.id,
            ),
        )
        self._db.commit()

    def remove_app(self, app_id: int) -> None:
        """Mark an app as removed (soft-delete)."""
        self._db.execute(
            "UPDATE apps SET status='removed', updated_at=? WHERE id=?",
            (self._now(), app_id),
        )
        self._db.commit()

    def delete_app(self, app_id: int) -> None:
        """Hard-delete an app and its version history."""
        self._db.execute("DELETE FROM apps WHERE id=?", (app_id,))
        self._db.commit()

    def get_app(self, app_id: int) -> AppRecord | None:
        row = self._db.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
        return self._row_to_app(row) if row else None

    def find_app(self, name: str, fmt: str) -> AppRecord | None:
        """Find an installed app by name and format."""
        row = self._db.execute(
            "SELECT * FROM apps WHERE name=? AND format=? AND status='installed'",
            (name, fmt),
        ).fetchone()
        return self._row_to_app(row) if row else None

    def list_apps(self, *, status: str | None = "installed") -> list[AppRecord]:
        """List apps, optionally filtered by status."""
        if status:
            rows = self._db.execute(
                "SELECT * FROM apps WHERE status=? ORDER BY name", (status,)
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM apps ORDER BY name"
            ).fetchall()
        return [self._row_to_app(r) for r in rows]

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------

    def add_version(self, rec: VersionRecord) -> int:
        rec.created_at = self._now()
        cur = self._db.execute(
            """INSERT INTO version_history
               (app_id, version, backup_path, action, created_at, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (rec.app_id, rec.version, rec.backup_path, rec.action,
             rec.created_at, rec.notes),
        )
        self._db.commit()
        rec.id = cur.lastrowid
        return rec.id  # type: ignore[return-value]

    def get_versions(self, app_id: int) -> list[VersionRecord]:
        rows = self._db.execute(
            "SELECT * FROM version_history WHERE app_id=? ORDER BY created_at DESC",
            (app_id,),
        ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def get_latest_backup(self, app_id: int) -> VersionRecord | None:
        row = self._db.execute(
            """SELECT * FROM version_history
               WHERE app_id=? AND backup_path IS NOT NULL
               ORDER BY created_at DESC LIMIT 1""",
            (app_id,),
        ).fetchone()
        return self._row_to_version(row) if row else None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_app(row: sqlite3.Row) -> AppRecord:
        return AppRecord(
            id=row["id"],
            name=row["name"],
            display_name=row["display_name"],
            format=row["format"],
            version=row["version"],
            architecture=row["architecture"],
            description=row["description"],
            install_path=row["install_path"],
            desktop_entry=row["desktop_entry"],
            icon_path=row["icon_path"],
            installed_at=row["installed_at"],
            updated_at=row["updated_at"],
            status=row["status"],
            metadata_json=row["metadata_json"],
        )

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> VersionRecord:
        return VersionRecord(
            id=row["id"],
            app_id=row["app_id"],
            version=row["version"],
            backup_path=row["backup_path"],
            action=row["action"],
            created_at=row["created_at"],
            notes=row["notes"],
        )
