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
from appdrop.gui.installed_view import InstalledView
from appdrop.gui.queue_view import QueueView
from appdrop.service import AppService

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level window for AppDrop."""

    def __init__(
        self,
        service: AppService | None = None,
        *,
        initial_files: list[Path] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service or AppService()
        self.setWindowTitle("AppDrop")
        self.setMinimumSize(700, 500)
        self._setup_ui()
        self._connect_signals()

        if initial_files:
            self._on_files_dropped(initial_files)

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

        # --- Installed Apps tab ---
        self._installed_view = InstalledView(self._service)
        self._tabs.addTab(self._installed_view, "Installed Apps")

        layout.addWidget(self._tabs)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage("Ready — drop packages to get started")

    def _connect_signals(self) -> None:
        self._drop_zone.files_dropped.connect(self._on_files_dropped)
        self._queue_view.proceed_requested.connect(self._on_proceed)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._installed_view.launch_requested.connect(self._on_launch_app)
        self._installed_view.uninstall_requested.connect(self._on_uninstall_app)
        self._installed_view.rollback_requested.connect(self._on_rollback_app)

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._installed_view.reload_data()

    def _on_launch_app(self, app_id: int) -> None:
        success, err = self._service.launch(app_id)
        if success:
            self._status_bar.showMessage("Application launched", 3000)
        else:
            ErrorDialog("Launch Error", "Could not launch application.", err, parent=self).exec()

    def _on_uninstall_app(self, app_id: int) -> None:
        try:
            result = self._service.uninstall(app_id)
            if result.success:
                self._status_bar.showMessage("Application uninstalled successfully", 5000)
                self._installed_view.reload_data()
            else:
                ErrorDialog(
                    "Uninstall Failed",
                    "Could not uninstall application.",
                    result.error,
                    parent=self,
                ).exec()
        except Exception as exc:
            log.exception("Uninstall exception")
            ErrorDialog("Uninstall Error", "An unexpected error occurred.", str(exc), parent=self).exec()

    def _on_rollback_app(self, app_id: int) -> None:
        try:
            result = self._service.rollback(app_id)
            if result.success:
                self._status_bar.showMessage("Application rolled back successfully", 5000)
                self._installed_view.reload_data()
            else:
                ErrorDialog(
                    "Rollback Failed",
                    "Could not roll back application.",
                    result.error,
                    parent=self,
                ).exec()
        except Exception as exc:
            log.exception("Rollback exception")
            ErrorDialog("Rollback Error", "An unexpected error occurred.", str(exc), parent=self).exec()

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

        # Execute confirmed operations
        self._execute_items(actionable, allow_downgrades=True)

    def _execute_items(self, items: list, *, allow_downgrades: bool = False) -> None:
        """Execute installation/update for confirmed items."""
        try:
            results = self._service.execute_queue(items, allow_downgrades=allow_downgrades)
            self._status_bar.showMessage("Operations completed")
            # Update queue view with results
            for i, item in enumerate(results):
                status = "✓ Done" if not item.info.error else f"✗ {item.info.error}"
                self._queue_view.update_item_status(i, status)
            self._installed_view.reload_data()
        except Exception as exc:
            log.exception("Error executing queue")
            ErrorDialog(
                "Installation Error",
                "An error occurred during installation.",
                str(exc),
                parent=self,
            ).exec()
