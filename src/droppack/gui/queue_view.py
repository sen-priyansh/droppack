"""Queue view — displays detected packages and proposed actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from droppack.service import QueueItem

log = logging.getLogger(__name__)

_COLUMNS = ("Name", "Version", "Format", "Action", "Status")


class QueueView(QWidget):
    """Table of packages pending installation or update.

    Emits :pyqtSignal:`proceed_requested` when the user clicks "Install"
    and :pyqtSignal:`clear_requested` when the user clicks "Clear".
    """

    proceed_requested = Signal()
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[QueueItem] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        header_layout = QHBoxLayout()
        self._title = QLabel("Package Queue")
        title_font = self._title.font()
        title_font.setPointSize(12)
        title_font.setBold(True)
        self._title.setFont(title_font)
        header_layout.addWidget(self._title)
        header_layout.addStretch()

        self._count_label = QLabel("0 packages")
        header_layout.addWidget(self._count_label)
        layout.addLayout(header_layout)

        # Table
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(self._clear_btn)

        self._install_btn = QPushButton("Install / Update")
        self._install_btn.setDefault(True)
        self._install_btn.clicked.connect(self._on_proceed)
        btn_layout.addWidget(self._install_btn)

        layout.addLayout(btn_layout)
        self._update_buttons()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_items(self, items: list[QueueItem]) -> None:
        """Append items to the queue and refresh the table."""
        self._items.extend(items)
        self._rebuild_table()

    def clear(self) -> None:
        """Remove all items from the queue."""
        self._items.clear()
        self._rebuild_table()

    def get_items(self) -> list[QueueItem]:
        return list(self._items)

    def update_item_status(self, index: int, status: str) -> None:
        """Update the Status column for a specific row."""
        if 0 <= index < self._table.rowCount():
            status_item = QTableWidgetItem(status)
            self._table.setItem(index, 4, status_item)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_table(self) -> None:
        self._table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            info = item.info
            self._table.setItem(row, 0, QTableWidgetItem(info.display_name))
            self._table.setItem(row, 1, QTableWidgetItem(info.version or "—"))
            self._table.setItem(row, 2, QTableWidgetItem(info.format_label))
            self._table.setItem(row, 3, QTableWidgetItem(item.display_action))

            # Status: show error or "Pending"
            if info.error:
                status = QTableWidgetItem(f"⚠ {info.error}")
                status.setForeground(QColor("#E65100"))
            else:
                status = QTableWidgetItem("Pending")
            self._table.setItem(row, 4, status)

        count = len(self._items)
        self._count_label.setText(f"{count} package{'s' if count != 1 else ''}")
        self._update_buttons()

    def _update_buttons(self) -> None:
        has_items = len(self._items) > 0
        self._clear_btn.setEnabled(has_items)
        actionable = any(i.can_proceed for i in self._items)
        self._install_btn.setEnabled(actionable)

    def _on_proceed(self) -> None:
        self.proceed_requested.emit()

    def _on_clear(self) -> None:
        self.clear()
        self.clear_requested.emit()
