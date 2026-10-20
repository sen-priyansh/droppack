"""Installed applications view — list, filter, inspect history, uninstall, and rollback."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from appdrop.gui.dialogs import HistoryDialog
from appdrop.registry import AppRecord

if TYPE_CHECKING:
    from appdrop.service import AppService

log = logging.getLogger(__name__)

_COLUMNS = ("Name", "Format", "Version", "Architecture", "Status")


class InstalledView(QWidget):
    """View displaying installed applications and management actions."""

    launch_requested = Signal(int)     # app_id
    uninstall_requested = Signal(int)  # app_id
    rollback_requested = Signal(int)   # app_id
    refresh_requested = Signal()

    def __init__(
        self,
        service: AppService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._apps: list[AppRecord] = []
        self._filtered_apps: list[AppRecord] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Top bar: search filter + refresh button
        top_bar = QHBoxLayout()

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter applications by name…")
        self._search_input.textChanged.connect(self._on_filter_changed)
        top_bar.addWidget(self._search_input)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.reload_data)
        top_bar.addWidget(self._refresh_btn)

        layout.addLayout(top_bar)

        # Applications table
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.setAlternatingRowColors(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(lambda r, c: self._on_launch())
        layout.addWidget(self._table)

        # Action bar at bottom
        action_bar = QHBoxLayout()

        self._count_label = QLabel("0 applications")
        action_bar.addWidget(self._count_label)
        action_bar.addStretch()

        self._launch_btn = QPushButton("Launch")
        self._launch_btn.setEnabled(False)
        self._launch_btn.clicked.connect(self._on_launch)
        action_bar.addWidget(self._launch_btn)

        self._history_btn = QPushButton("View History")
        self._history_btn.setEnabled(False)
        self._history_btn.clicked.connect(self._on_view_history)
        action_bar.addWidget(self._history_btn)

        self._rollback_btn = QPushButton("Rollback")
        self._rollback_btn.setEnabled(False)
        self._rollback_btn.setToolTip("Roll back AppImage to previous backup")
        self._rollback_btn.clicked.connect(self._on_rollback)
        action_bar.addWidget(self._rollback_btn)

        self._uninstall_btn = QPushButton("Uninstall")
        self._uninstall_btn.setEnabled(False)
        self._uninstall_btn.setStyleSheet("QPushButton { color: #C62828; }")
        self._uninstall_btn.clicked.connect(self._on_uninstall)
        action_bar.addWidget(self._uninstall_btn)

        layout.addLayout(action_bar)

    # ------------------------------------------------------------------
    # Data loading & filtering
    # ------------------------------------------------------------------

    def reload_data(self) -> None:
        """Fetch installed applications from service and refresh display."""
        try:
            self._apps = self._service.list_installed()
        except Exception as exc:
            log.exception("Failed to load installed apps: %s", exc)
            self._apps = []
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._search_input.text().strip().lower()
        if not query:
            self._filtered_apps = list(self._apps)
        else:
            self._filtered_apps = [
                a for a in self._apps
                if query in (a.display_name or a.name).lower()
                or query in a.format.lower()
            ]
        self._render_table()

    def _render_table(self) -> None:
        self._table.setRowCount(len(self._filtered_apps))
        for row, app in enumerate(self._filtered_apps):
            self._table.setItem(row, 0, QTableWidgetItem(app.display_name or app.name))
            self._table.setItem(row, 1, QTableWidgetItem(app.format.upper()))
            self._table.setItem(row, 2, QTableWidgetItem(app.version or "—"))
            self._table.setItem(row, 3, QTableWidgetItem(app.architecture or "—"))
            self._table.setItem(row, 4, QTableWidgetItem(app.status.capitalize()))

        count = len(self._filtered_apps)
        self._count_label.setText(f"{count} application{'s' if count != 1 else ''}")
        self._on_selection_changed()

    def _on_filter_changed(self) -> None:
        self._apply_filter()

    def _selected_app(self) -> AppRecord | None:
        selected_rows = self._table.selectionModel().selectedRows()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        if 0 <= row < len(self._filtered_apps):
            return self._filtered_apps[row]
        return None

    # ------------------------------------------------------------------
    # Button state management
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        app = self._selected_app()
        if app is None:
            self._launch_btn.setEnabled(False)
            self._history_btn.setEnabled(False)
            self._rollback_btn.setEnabled(False)
            self._uninstall_btn.setEnabled(False)
            return

        self._launch_btn.setEnabled(True)
        self._history_btn.setEnabled(True)
        self._uninstall_btn.setEnabled(True)

        # Rollback only enabled for AppImages with a recorded backup
        can_rollback = False
        if app.format == "appimage" and app.id is not None:
            backup = self._service._registry.get_latest_backup(app.id)
            if backup and backup.backup_path:
                can_rollback = True
        self._rollback_btn.setEnabled(can_rollback)

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def _on_launch(self) -> None:
        app = self._selected_app()
        if not app or app.id is None:
            return
        self.launch_requested.emit(app.id)

    def _on_view_history(self) -> None:
        app = self._selected_app()
        if not app or app.id is None:
            return
        history = self._service.get_version_history(app.id)
        dialog = HistoryDialog(app.display_name or app.name, history, parent=self)
        dialog.exec()

    def _on_rollback(self) -> None:
        app = self._selected_app()
        if not app or app.id is None:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Rollback",
            f"Are you sure you want to roll back '{app.display_name or app.name}' "
            "to its previous version?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.rollback_requested.emit(app.id)

    def _on_uninstall(self) -> None:
        app = self._selected_app()
        if not app or app.id is None:
            return

        warning_extra = ""
        if app.format == "deb":
            warning_extra = (
                "\n\nNote: This is a Debian system package. Uninstallation will "
                "invoke APT and will require administrator (root) password."
            )

        reply = QMessageBox.warning(
            self,
            "Confirm Uninstall",
            f"Are you sure you want to uninstall '{app.display_name or app.name}'?{warning_extra}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.uninstall_requested.emit(app.id)
