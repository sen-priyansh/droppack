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

from appdrop.backends.appimage import AppImageBackend, InstallResult
from appdrop.detect import PackageFormat, PackageInfo, detect
from appdrop.identity import Confidence, IdentityResolver
from appdrop.registry import Registry

log = logging.getLogger(__name__)


class DropAction(enum.Enum):
    """What AppDrop proposes to do with a dropped file."""

    INSTALL = "Install"
    UPDATE = "Update"
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
        return self.action.value

    @property
    def can_proceed(self) -> bool:
        """Whether the item has enough information to proceed."""
        return self.info.format != PackageFormat.UNKNOWN and self.info.error is None


class AppService:
    """Facade that ties detection, identity matching, and backends together."""

    def __init__(self, *, root_override: Path | None = None) -> None:
        self._root = root_override
        self._registry = Registry(root_override=root_override)
        self._registry.open()
        self._identity = IdentityResolver(self._registry)
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
            return QueueItem(
                info=info,
                action=DropAction.UPDATE,
                match_confidence=match.confidence.value,
                existing_version=match.existing.version if match.existing else None,
            )

        return QueueItem(
            info=info,
            action=DropAction.INSTALL,
            match_confidence=match.confidence.value,
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_queue(self, items: list[QueueItem]) -> list[QueueItem]:
        """Execute the proposed actions for all queue items."""
        for item in items:
            if not item.can_proceed:
                continue

            if item.info.format == PackageFormat.APPIMAGE:
                self._execute_appimage(item)
            elif item.info.format == PackageFormat.DEB:
                # Deb backend implemented in Milestone 5
                item.info.error = "Debian package installation not yet implemented"

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
        else:
            return InstallResult(success=False, error="Uninstall not supported for this format")

    def rollback(self, app_id: int) -> InstallResult:
        """Roll back an application to its previous version."""
        return self._appimage.rollback(app_id)

    def get_version_history(self, app_id: int) -> list:
        """Return version history for an application."""
        return self._registry.get_versions(app_id)
