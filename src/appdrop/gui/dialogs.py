"""Confirmation and information dialogs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from appdrop.service import QueueItem


class ConfirmDialog(QDialog):
    """Ask the user to confirm a batch of package operations."""

    def __init__(
        self,
        items: list[QueueItem],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm Operations")
        self.setMinimumWidth(480)
        self._items = items
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        header = QLabel("The following operations will be performed:")
        header_font = header.font()
        header_font.setBold(True)
        header.setFont(header_font)
        layout.addWidget(header)

        # Scrollable list of operations
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        deb_items = [i for i in self._items if i.info.format.value == "Debian Package" and i.can_proceed]
        appimage_items = [i for i in self._items if i.info.format.value == "AppImage" and i.can_proceed]

        if appimage_items:
            section = QLabel("AppImage (user-level, no root required):")
            section_font = section.font()
            section_font.setItalic(True)
            section.setFont(section_font)
            scroll_layout.addWidget(section)
            for item in appimage_items:
                scroll_layout.addWidget(self._make_item_row(item))

        if deb_items:
            section = QLabel("Debian packages (requires administrator privileges):")
            section_font = section.font()
            section_font.setItalic(True)
            section.setFont(section_font)
            scroll_layout.addWidget(section)
            for item in deb_items:
                scroll_layout.addWidget(self._make_item_row(item))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Warning for deb packages
        if deb_items:
            warning = QLabel(
                "⚠ Debian package installation requires root privileges.\n"
                "You will be prompted for your password."
            )
            warning.setStyleSheet("color: #E65100; padding: 8px;")
            warning.setWordWrap(True)
            layout.addWidget(warning)

        # Warning for downgrades
        has_downgrades = any(getattr(i, "action", None) and i.action.name == "DOWNGRADE" for i in self._items)
        if has_downgrades:
            dw_warning = QLabel(
                "⚠ WARNING: One or more packages will be DOWNGRADED to an older version.\n"
                "Downgrading packages can lead to system instability."
            )
            dw_warning.setStyleSheet("color: #C62828; font-weight: bold; background: #FFEBEE; padding: 8px; border-radius: 4px;")
            dw_warning.setWordWrap(True)
            layout.addWidget(dw_warning)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Proceed")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_item_row(self, item: QueueItem) -> QWidget:
        container = QWidget()
        v_layout = QVBoxLayout(container)
        v_layout.setContentsMargins(16, 2, 8, 2)
        v_layout.setSpacing(2)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)

        action = QLabel(f"  •  {item.display_action}")
        action.setFixedWidth(80)
        row_layout.addWidget(action)

        name = QLabel(f"<b>{item.info.display_name}</b>")
        if item.info.sha256:
            name.setToolTip(f"SHA-256: {item.info.sha256}")
        row_layout.addWidget(name)

        version = QLabel(item.info.version or "")
        version.setStyleSheet("color: #666;")
        row_layout.addWidget(version)

        row_layout.addStretch()
        v_layout.addWidget(row)

        if item.info.dependencies:
            deps_text = ", ".join(item.info.dependencies[:4])
            if len(item.info.dependencies) > 4:
                deps_text += f" (+{len(item.info.dependencies) - 4} more)"
            deps_label = QLabel(f"    Dependencies: {deps_text}")
            deps_label.setStyleSheet("color: #78909C; font-size: 11px;")
            v_layout.addWidget(deps_label)

        return container


class ErrorDialog(QDialog):
    """Display one or more error messages."""

    def __init__(
        self,
        title: str,
        message: str,
        details: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self._setup_ui(message, details)

    def _setup_ui(self, message: str, details: str | None) -> None:
        layout = QVBoxLayout(self)

        msg = QLabel(message)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        if details:
            det = QLabel(details)
            det.setWordWrap(True)
            det.setStyleSheet(
                "background-color: #F5F5F5; padding: 8px; "
                "font-family: monospace; font-size: 11px;"
            )
            layout.addWidget(det)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class HistoryDialog(QDialog):
    """Display version and action history for an application."""

    def __init__(
        self,
        app_name: str,
        history: list,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"History — {app_name}")
        self.setMinimumWidth(560)
        self.setMinimumHeight(320)
        self._history = history
        self._setup_ui()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView

        layout = QVBoxLayout(self)

        columns = ("Date / Time", "Action", "Version", "Notes")
        table = QTableWidget(len(self._history), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setAlternatingRowColors(True)

        for row, item in enumerate(self._history):
            date_str = item.created_at[:19].replace("T", " ") if hasattr(item, "created_at") else ""
            table.setItem(row, 0, QTableWidgetItem(date_str))
            table.setItem(row, 1, QTableWidgetItem(getattr(item, "action", "").upper()))
            table.setItem(row, 2, QTableWidgetItem(getattr(item, "version", "") or "—"))
            table.setItem(row, 3, QTableWidgetItem(getattr(item, "notes", "") or ""))

        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
