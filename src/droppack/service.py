"""Application service — orchestrates detection, identity, and installation.

The GUI calls methods on ``AppService``; the service delegates to the
appropriate backend and returns results.  The service never imports GUI
code directly.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path

from droppack.backends.appimage import AppImageBackend, InstallResult
from droppack.backends.deb import CommandRunner, DebBackend, DebInstallResult
from droppack.detect import PackageFormat, PackageInfo, detect
from droppack.identity import Confidence, IdentityResolver
from droppack.registry import Registry

log = logging.getLogger(__name__)


class DropAction(enum.Enum):
    """What DropPack proposes to do with a dropped file."""

    INSTALL = "Install"
    UPDATE = "Update"
    DOWNGRADE = "Downgrade (Warning)"
    UNKNOWN = "Unknown"


@dataclass
class QueueItem:
    """A detected package paired with the proposed action."""

    info: PackageInfo
    action: DropAction = DropAction.UNKNOWN
    match_confidence: str = ""
    existing_version: str | None = None

    @property
    def display_action(self) -> str:
        if self.action == DropAction.UPDATE and self.existing_version:
            return f"Update ({self.existing_version} → {self.info.version or '?'})"
        if self.action == DropAction.DOWNGRADE and self.existing_version:
            return f"Downgrade ⚠ ({self.existing_version} → {self.info.version or '?'})"
        return self.action.value

    @property
    def can_proceed(self) -> bool:
        """Whether the item has enough information to proceed."""
        return self.info.format != PackageFormat.UNKNOWN and self.info.error is None


class AppService:
    """Facade that ties detection, identity matching, and backends together."""

    def __init__(
        self,
        *,
        root_override: Path | None = None,
        deb_runner: CommandRunner | None = None,
        deb_query_runner: CommandRunner | None = None,
    ) -> None:
        self._root = root_override
        self._registry = Registry(root_override=root_override)
        self._registry.open()
        self._deb = DebBackend(
            self._registry,
            runner=deb_runner,
            query_runner=deb_query_runner,
        )
        self._identity = IdentityResolver(self._registry, deb_backend=self._deb)
        self._appimage = AppImageBackend(self._registry, root_override=root_override)

    def close(self) -> None:
        """Release database resources."""
        self._registry.close()

    # ------------------------------------------------------------------
    # Detection + identity resolution
    # ------------------------------------------------------------------

    def process_files(self, paths: list[Path]) -> list[QueueItem]:
        """Detect format and metadata for each path, then resolve identity."""
        items: list[QueueItem] = []
        for p in paths:
            info = detect(p)
            item = self._build_queue_item(info)
            items.append(item)
        return items

    def _build_queue_item(self, info: PackageInfo) -> QueueItem:
        if info.format == PackageFormat.UNKNOWN or info.error:
            return QueueItem(info=info, action=DropAction.UNKNOWN)

        match = self._identity.resolve(info)

        if match.is_update:
            existing_ver = match.existing.version if match.existing else None

            # Check for downgrade on deb packages
            if info.format == PackageFormat.DEB and info.name and info.version:
                is_dw, cur_ver = self._deb.check_downgrade(info.name, info.version)
                if is_dw:
                    return QueueItem(
                        info=info,
                        action=DropAction.DOWNGRADE,
                        match_confidence=match.confidence.value,
                        existing_version=cur_ver or existing_ver,
                    )

            return QueueItem(
                info=info,
                action=DropAction.UPDATE,
                match_confidence=match.confidence.value,
                existing_version=existing_ver,
            )

        return QueueItem(
            info=info,
            action=DropAction.INSTALL,
            match_confidence=match.confidence.value,
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_queue(
        self,
        items: list[QueueItem],
        *,
        allow_downgrades: bool = False,
    ) -> list[QueueItem]:
        """Execute the proposed actions for all queue items."""
        for item in items:
            if not item.can_proceed:
                continue

            if item.info.format == PackageFormat.APPIMAGE:
                self._execute_appimage(item)
            elif item.info.format == PackageFormat.DEB:
                self._execute_deb(item, allow_downgrade=allow_downgrades)

        return items

    def _execute_appimage(self, item: QueueItem) -> None:
        """Execute an AppImage install or update."""
        if item.action == DropAction.UPDATE:
            match = self._identity.resolve(item.info)
            if match.existing:
                result = self._appimage.update(item.info, match.existing)
            else:
                result = self._appimage.install(item.info)
        else:
            result = self._appimage.install(item.info)

        if not result.success:
            item.info.error = result.error

    def _execute_deb(self, item: QueueItem, *, allow_downgrade: bool = False) -> None:
        """Execute Debian package installation or upgrade via APT."""
        result = self._deb.install(
            item.info,
            allow_downgrade=allow_downgrade or (item.action != DropAction.DOWNGRADE),
        )
        if not result.success:
            item.info.error = result.error

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def list_installed(self) -> list:
        """Return all installed applications."""
        return self._registry.list_apps()

    def uninstall(self, app_id: int) -> InstallResult:
        """Uninstall an application by its registry id."""
        app = self._registry.get_app(app_id)
        if app is None:
            return InstallResult(success=False, error="Application not found")

        if app.format == "appimage":
            return self._appimage.uninstall(app_id)
        elif app.format == "deb":
            res = self._deb.uninstall(app_id)
            return InstallResult(success=res.success, error=res.error)
        else:
            return InstallResult(success=False, error="Uninstall not supported for this format")

    def rollback(self, app_id: int) -> InstallResult:
        """Roll back an application to its previous version."""
        return self._appimage.rollback(app_id)

    def get_version_history(self, app_id: int) -> list:
        """Return version history for an application."""
        return self._registry.get_versions(app_id)

    def launch(self, app_id: int) -> tuple[bool, str | None]:
        """Launch an installed application in the background."""
        import shutil
        import subprocess

        app = self._registry.get_app(app_id)
        if not app:
            return False, "Application not found"

        if app.format == "appimage" and app.install_path:
            p = Path(app.install_path)
            if not p.exists():
                return False, f"Executable file missing: {p}"
            try:
                subprocess.Popen([str(p)], start_new_session=True)
                return True, None
            except OSError as exc:
                return False, f"Failed to launch AppImage: {exc}"

        if app.format == "deb":
            gtk_launch = shutil.which("gtk-launch")
            if gtk_launch:
                try:
                    subprocess.Popen([gtk_launch, app.name], start_new_session=True)
                    return True, None
                except OSError:
                    pass

            bin_path = shutil.which(app.name)
            if bin_path:
                try:
                    subprocess.Popen([bin_path], start_new_session=True)
                    return True, None
                except OSError as exc:
                    return False, f"Failed to execute {app.name}: {exc}"

            return False, f"Cannot launch {app.name}: desktop launcher or binary not found"

        return False, "Unsupported application format"
