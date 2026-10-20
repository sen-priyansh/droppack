"""Drop zone widget — accepts drag-and-drop of AppImage and .deb files."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QFont, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

log = logging.getLogger(__name__)

_ACCEPTED_SUFFIXES = {".appimage", ".deb"}


class DropZone(QWidget):
    """Large drag-and-drop target area.

    Emits :pyqtSignal:`files_dropped` with a list of local file paths
    when the user drops supported files onto it.
    """

    files_dropped = Signal(list)  # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumSize(400, 200)
        self._hovering = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._icon_label = QLabel("📦")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_font = QFont()
        icon_font.setPointSize(48)
        self._icon_label.setFont(icon_font)
        layout.addWidget(self._icon_label)

        self._text_label = QLabel("Drop .AppImage or .deb files here")
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text_font = QFont()
        text_font.setPointSize(14)
        self._text_label.setFont(text_font)
        layout.addWidget(self._text_label)

        self._update_style()

    # ------------------------------------------------------------------
    # Drag-and-drop events
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # Accept if at least one file has a supported suffix
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.suffix.lower() in _ACCEPTED_SUFFIXES:
                        event.acceptProposedAction()
                        self._hovering = True
                        self._update_style()
                        return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._hovering = False
        self._update_style()

    def dropEvent(self, event: QDropEvent) -> None:
        self._hovering = False
        self._update_style()

        paths: list[Path] = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.suffix.lower() in _ACCEPTED_SUFFIXES:
                    paths.append(path)
                else:
                    log.info("Ignoring unsupported file: %s", path.name)

        if paths:
            log.info("Dropped %d file(s): %s", len(paths),
                     ", ".join(p.name for p in paths))
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()

    # ------------------------------------------------------------------
    # Appearance
    # ------------------------------------------------------------------

    def _update_style(self) -> None:
        if self._hovering:
            self.setStyleSheet(
                "DropZone {"
                "  border: 3px dashed #4FC3F7;"
                "  border-radius: 16px;"
                "  background-color: #E3F2FD;"
                "}"
            )
            self._text_label.setText("Release to add packages")
        else:
            self.setStyleSheet(
                "DropZone {"
                "  border: 3px dashed #90A4AE;"
                "  border-radius: 16px;"
                "  background-color: #F5F5F5;"
                "}"
            )
            self._text_label.setText("Drop .AppImage or .deb files here")
