"""Main application window."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from appdrop.gui.dialogs import ConfirmDialog, ErrorDialog
from appdrop.gui.drop_zone import DropZone
from appdrop.gui.queue_view import QueueView
from appdrop.service import AppService

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level window for AppDrop."""

    def __init__(
        self,
        service: AppService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service or AppService()
        self.setWindowTitle("AppDrop")
        self.setMinimumSize(700, 500)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Tab widget for different views
        self._tabs = QTabWidget()

        # --- Drop & Install tab ---
        install_tab = QWidget()
        install_layout = QVBoxLayout(install_tab)

        # Splitter: drop zone on top, queue on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        self._drop_zone = DropZone()
        splitter.addWidget(self._drop_zone)

        self._queue_view = QueueView()
        splitter.addWidget(self._queue_view)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        install_layout.addWidget(splitter)
        self._tabs.addTab(install_tab, "Install")

        # --- Installed Apps tab (placeholder for Milestone 6) ---
        installed_tab = QWidget()
        installed_layout = QVBoxLayout(installed_tab)
        from PySide6.QtWidgets import QLabel
        placeholder = QLabel("Installed applications will appear here.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        installed_layout.addWidget(placeholder)
        self._tabs.addTab(installed_tab, "Installed Apps")

        layout.addWidget(self._tabs)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready — drop packages to get started")

    def _connect_signals(self) -> None:
        self._drop_zone.files_dropped.connect(self._on_files_dropped)
        self._queue_view.proceed_requested.connect(self._on_proceed)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_files_dropped(self, paths: list[Path]) -> None:
        """Process dropped files through the service and display results."""
        self._status_bar.showMessage(f"Detecting {len(paths)} file(s)…")
        try:
            items = self._service.process_files(paths)
            self._queue_view.add_items(items)

            errors = [i for i in items if i.info.error]
            ok = len(items) - len(errors)
            msg = f"Detected {ok} package(s)"
            if errors:
                msg += f", {len(errors)} with warnings"
            self._status_bar.showMessage(msg, 5000)
        except Exception as exc:
            log.exception("Error processing dropped files")
            ErrorDialog(
                "Detection Error",
                "Failed to process one or more files.",
                str(exc),
                parent=self,
            ).exec()
            self._status_bar.showMessage("Error during detection")

    def _on_proceed(self) -> None:
        """Show confirmation dialog and execute approved operations."""
        items = self._queue_view.get_items()
        actionable = [i for i in items if i.can_proceed]

        if not actionable:
            self._status_bar.showMessage("No actionable packages in queue")
            return

        dialog = ConfirmDialog(actionable, parent=self)
        if dialog.exec() != ConfirmDialog.DialogCode.Accepted:
            self._status_bar.showMessage("Operation cancelled")
            return

        # Execute (Milestone 3+ will actually install)
        self._execute_items(actionable)

    def _execute_items(self, items: list) -> None:
        """Execute installation/update for confirmed items."""
        try:
            results = self._service.execute_queue(items)
            self._status_bar.showMessage("Operations completed")
            # Update queue view with results
            for i, item in enumerate(results):
                status = "✓ Done" if not item.info.error else f"✗ {item.info.error}"
                self._queue_view.update_item_status(i, status)
        except NotImplementedError:
            self._status_bar.showMessage(
                "Installation will be available in a future milestone"
            )
            ErrorDialog(
                "Not Yet Implemented",
                "Package installation is not yet available.\n\n"
                "Detection and queuing are working — installation "
                "will be implemented in Milestone 3.",
                parent=self,
            ).exec()
        except Exception as exc:
            log.exception("Error executing queue")
            ErrorDialog(
                "Installation Error",
                "An error occurred during installation.",
                str(exc),
                parent=self,
            ).exec()
