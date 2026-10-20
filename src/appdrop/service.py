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

from appdrop.detect import PackageFormat, PackageInfo, detect

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

    @property
    def display_action(self) -> str:
        return self.action.value

    @property
    def can_proceed(self) -> bool:
        """Whether the item has enough information to proceed."""
        return self.info.format != PackageFormat.UNKNOWN and self.info.error is None


class AppService:
    """Facade that ties detection, identity matching, and backends together.

    Milestone 2 supports detection and queuing only.
    """

    def __init__(self, *, root_override: Path | None = None) -> None:
        self._root_override = root_override

    # ------------------------------------------------------------------
    # Detection (Milestone 2)
    # ------------------------------------------------------------------

    def process_files(self, paths: list[Path]) -> list[QueueItem]:
        """Detect format and metadata for each path.

        Returns a :class:`QueueItem` for every path, even those that
        could not be identified (their ``info.error`` will be set).
        """
        items: list[QueueItem] = []
        for p in paths:
            info = detect(p)
            action = self._propose_action(info)
            items.append(QueueItem(info=info, action=action))
        return items

    def _propose_action(self, info: PackageInfo) -> DropAction:
        """Determine install vs. update.

        Milestone 2: always proposes INSTALL since the registry is not
        yet connected.  Identity matching is added in Milestone 4.
        """
        if info.format == PackageFormat.UNKNOWN:
            return DropAction.UNKNOWN
        return DropAction.INSTALL

    # ------------------------------------------------------------------
    # Installation stubs (implemented in later milestones)
    # ------------------------------------------------------------------

    def execute_queue(self, items: list[QueueItem]) -> list[QueueItem]:
        """Execute the proposed actions for all queue items.

        Milestone 2 stub — raises NotImplementedError.
        """
        raise NotImplementedError("Installation is not yet implemented")
