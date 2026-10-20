"""AppImage backend — install, update, rollback, and uninstall.

All operations are user-level (no root required).  AppImages are stored
in ``~/.local/share/appdrop/apps/``, and previous versions are kept in
``~/.local/share/appdrop/backups/`` until explicitly purged.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from appdrop.config import apps_dir, backups_dir, cache_dir
from appdrop.desktop import (
    create_desktop_entry,
    install_icon,
    install_icon_bytes,
    remove_desktop_entry,
    remove_icon,
)
from appdrop.detect import PackageInfo
from appdrop.registry import AppRecord, Registry, VersionRecord

log = logging.getLogger(__name__)


@dataclass
class InstallResult:
    """Outcome of an AppImage backend operation."""

    success: bool
    install_path: Path | None = None
    desktop_entry: Path | None = None
    error: str | None = None


class AppImageBackend:
    """Manages AppImage lifecycle: install, update, rollback, uninstall."""

    def __init__(
        self,
        registry: Registry,
        *,
        root_override: Path | None = None,
    ) -> None:
        self._registry = registry
        self._root = root_override

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def install(self, info: PackageInfo) -> InstallResult:
        """Install an AppImage as a new application.

        1. Copy the file to the managed apps directory.
        2. Make it executable.
        3. Create a .desktop entry.
        4. Register in the database.
        """
        dest_dir = apps_dir(self._root)
        dest_dir.mkdir(parents=True, exist_ok=True)

        app_name = info.display_name
        dest = dest_dir / info.filepath.name

        # Stage to a temp file first, then atomic rename
        staging = cache_dir(self._root)
        staging.mkdir(parents=True, exist_ok=True)
        staging_path = staging / f".staging-{info.filepath.name}"

        try:
            # Stage
            shutil.copy2(str(info.filepath), str(staging_path))

            # Make executable
            staging_path.chmod(
                staging_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
            )

            # Atomic move to destination
            if dest.exists():
                return InstallResult(
                    success=False,
                    error=f"File already exists: {dest.name}. Use update instead.",
                )

            shutil.move(str(staging_path), str(dest))

        except OSError as exc:
            # Clean up staging
            if staging_path.exists():
                staging_path.unlink()
            return InstallResult(success=False, error=str(exc))

        # Icon handling
        icon_path = None
        if info.icon_bytes:
            icon_path = install_icon_bytes(
                info.icon_bytes,
                info.icon_format or "png",
                app_name,
                root_override=self._root,
            )

        # Desktop entry
        desktop_path = create_desktop_entry(
            app_name=app_name,
            exec_path=dest,
            icon_path=icon_path,
            comment=info.description,
            root_override=self._root,
        )

        # Register
        rec = AppRecord(
            name=info.name or app_name,
            display_name=app_name,
            format="appimage",
            version=info.version,
            architecture=info.architecture,
            description=info.description,
            install_path=str(dest),
            desktop_entry=str(desktop_path),
            icon_path=str(icon_path) if icon_path else None,
            status="installed",
        )
        app_id = self._registry.add_app(rec)

        self._registry.add_version(VersionRecord(
            app_id=app_id,
            version=info.version,
            action="install",
            notes=f"Installed from {info.filepath.name}",
        ))

        log.info("Installed AppImage: %s → %s", info.filepath.name, dest)
        return InstallResult(
            success=True,
            install_path=dest,
            desktop_entry=desktop_path,
        )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, info: PackageInfo, existing: AppRecord) -> InstallResult:
        """Update an existing AppImage, preserving the previous version.

        1. Back up the current version.
        2. Stage the new version.
        3. Replace the installed file.
        4. Update the registry.
        """
        if existing.install_path is None:
            return InstallResult(success=False, error="No install path recorded")

        current_path = Path(existing.install_path)
        backup_dir = backups_dir(self._root)
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Back up current version
        backup_name = f"{existing.name}-{existing.version or 'unknown'}-{existing.id}.AppImage"
        backup_path = backup_dir / backup_name

        staging = cache_dir(self._root)
        staging.mkdir(parents=True, exist_ok=True)
        staging_path = staging / f".staging-{info.filepath.name}"

        try:
            # Stage new version first (validates it's copyable)
            shutil.copy2(str(info.filepath), str(staging_path))
            staging_path.chmod(
                staging_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
            )

            # Back up current version
            if current_path.exists():
                shutil.copy2(str(current_path), str(backup_path))

            # Replace with new version
            dest = current_path
            if dest.name != info.filepath.name:
                # Name changed; use new name, remove old
                dest = apps_dir(self._root) / info.filepath.name
            shutil.move(str(staging_path), str(dest))

            # Remove old file if name changed
            if current_path != dest and current_path.exists():
                current_path.unlink()

        except OSError as exc:
            if staging_path.exists():
                staging_path.unlink()
            return InstallResult(success=False, error=str(exc))

        # Update icon if extracted
        icon_path = Path(existing.icon_path) if existing.icon_path else None
        if info.icon_bytes:
            icon_path = install_icon_bytes(
                info.icon_bytes,
                info.icon_format or "png",
                existing.display_name or existing.name,
                root_override=self._root,
            )

        # Update desktop entry
        desktop_path = create_desktop_entry(
            app_name=existing.display_name or existing.name,
            exec_path=dest,
            icon_path=icon_path,
            comment=info.description or existing.description,
            root_override=self._root,
        )

        # Update registry
        old_version = existing.version
        existing.version = info.version
        existing.install_path = str(dest)
        existing.desktop_entry = str(desktop_path)
        if icon_path:
            existing.icon_path = str(icon_path)
        existing.description = info.description or existing.description
        self._registry.update_app(existing)

        self._registry.add_version(VersionRecord(
            app_id=existing.id,  # type: ignore[arg-type]
            version=old_version,
            backup_path=str(backup_path) if backup_path.exists() else None,
            action="update",
            notes=f"Updated from {old_version or '?'} to {info.version or '?'}",
        ))

        # Retention rule: keep only the most recent backup
        if existing.id:
            self.clean_old_backups(existing.id, keep_count=1)

        log.info("Updated AppImage: %s → %s", existing.name, dest)
        return InstallResult(
            success=True,
            install_path=dest,
            desktop_entry=desktop_path,
        )

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self, app_id: int) -> InstallResult:
        """Roll back to the most recent backup.

        1. Find the latest backup.
        2. Replace the current file with the backup.
        3. Update the registry.
        """
        app = self._registry.get_app(app_id)
        if app is None:
            return InstallResult(success=False, error="App not found")

        backup_rec = self._registry.get_latest_backup(app_id)
        if backup_rec is None or backup_rec.backup_path is None:
            return InstallResult(success=False, error="No backup available for rollback")

        backup_path = Path(backup_rec.backup_path)
        if not backup_path.exists():
            return InstallResult(success=False, error=f"Backup file missing: {backup_path}")

        current_path = Path(app.install_path) if app.install_path else None

        try:
            if current_path and current_path.exists():
                current_path.unlink()
            dest = apps_dir(self._root) / backup_path.name
            shutil.copy2(str(backup_path), str(dest))
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        except OSError as exc:
            return InstallResult(success=False, error=str(exc))

        # Update desktop entry
        desktop_path = create_desktop_entry(
            app_name=app.display_name or app.name,
            exec_path=dest,
            root_override=self._root,
        )

        # Update registry
        app.version = backup_rec.version
        app.install_path = str(dest)
        app.desktop_entry = str(desktop_path)
        self._registry.update_app(app)

        self._registry.add_version(VersionRecord(
            app_id=app_id,
            version=backup_rec.version,
            action="rollback",
            notes=f"Rolled back to version {backup_rec.version or '?'}",
        ))

        log.info("Rolled back %s to version %s", app.name, backup_rec.version)
        return InstallResult(success=True, install_path=dest, desktop_entry=desktop_path)

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self, app_id: int) -> InstallResult:
        """Uninstall an AppImage, removing files and desktop entry.

        Does NOT remove backups — those are preserved for manual recovery.
        """
        app = self._registry.get_app(app_id)
        if app is None:
            return InstallResult(success=False, error="App not found")

        errors: list[str] = []

        # Remove installed file
        if app.install_path:
            install_p = Path(app.install_path)
            if install_p.exists():
                # Safety: verify the file is inside our managed directory
                managed = apps_dir(self._root)
                try:
                    install_p.relative_to(managed)
                except ValueError:
                    return InstallResult(
                        success=False,
                        error=f"Refusing to delete file outside managed directory: {install_p}",
                    )
                try:
                    install_p.unlink()
                except OSError as exc:
                    errors.append(f"Could not remove file: {exc}")

        # Remove desktop entry
        remove_desktop_entry(app.display_name or app.name, root_override=self._root)

        # Remove icon
        remove_icon(app.display_name or app.name, root_override=self._root)

        # Update registry
        self._registry.remove_app(app_id)

        self._registry.add_version(VersionRecord(
            app_id=app_id,
            version=app.version,
            action="uninstall",
            notes="Uninstalled by user",
        ))

        if errors:
            return InstallResult(success=False, error="; ".join(errors))

        log.info("Uninstalled AppImage: %s", app.name)
        return InstallResult(success=True)

    def clean_old_backups(self, app_id: int, keep_count: int = 1) -> int:
        """Remove older backups exceeding *keep_count*. Returns count deleted."""
        versions = self._registry.get_versions(app_id)
        with_backup = [v for v in versions if v.backup_path]
        if len(with_backup) <= keep_count:
            return 0

        to_remove = with_backup[keep_count:]
        deleted = 0
        for v in to_remove:
            if v.backup_path:
                p = Path(v.backup_path)
                if p.exists():
                    try:
                        p.unlink()
                        deleted += 1
                        log.info("Cleaned old backup: %s", p)
                    except OSError:
                        pass
        return deleted
