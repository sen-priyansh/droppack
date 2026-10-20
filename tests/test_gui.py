"""GUI tests running offscreen via PySide6."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure Qt runs headlessly in test runner
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from appdrop.detect import PackageFormat, PackageInfo
from appdrop.gui.dialogs import ConfirmDialog, ErrorDialog, HistoryDialog
from appdrop.gui.drop_zone import DropZone
from appdrop.gui.installed_view import InstalledView
from appdrop.gui.main_window import MainWindow
from appdrop.gui.queue_view import QueueView
from appdrop.registry import AppRecord, Registry, VersionRecord
from appdrop.service import AppService, DropAction, QueueItem


@pytest.fixture(scope="session")
def qapp():
    """Ensure a single QApplication instance exists for GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def service(tmp_root: Path):
    svc = AppService(root_override=tmp_root)
    yield svc
    svc.close()


# ---------------------------------------------------------------------------
# DropZone tests
# ---------------------------------------------------------------------------


class TestDropZone:
    def test_init(self, qapp):
        dz = DropZone()
        assert dz.acceptDrops()

    def test_drag_and_drop_event(self, qapp, tmp_path: Path):
        dz = DropZone()
        received = []
        dz.files_dropped.connect(received.extend)

        test_file = tmp_path / "app.AppImage"
        test_file.touch()

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(test_file))])

        # Drag enter
        drag_event = QDragEnterEvent(
            QPoint(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dz.dragEnterEvent(drag_event)
        assert drag_event.isAccepted()

        # Drop
        drop_event = QDropEvent(
            QPointF(10, 10),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dz.dropEvent(drop_event)
        assert drop_event.isAccepted()
        assert len(received) == 1
        assert received[0] == test_file


# ---------------------------------------------------------------------------
# QueueView tests
# ---------------------------------------------------------------------------


class TestQueueView:
    def test_add_and_clear_items(self, qapp, tmp_path: Path):
        qv = QueueView()
        info = PackageInfo(
            filepath=tmp_path / "foo.AppImage",
            format=PackageFormat.APPIMAGE,
            name="Foo",
            version="1.0",
        )
        item = QueueItem(info=info, action=DropAction.INSTALL)

        qv.add_items([item])
        assert len(qv.get_items()) == 1
        assert qv._table.rowCount() == 1

        qv.update_item_status(0, "✓ Done")
        assert qv._table.item(0, 4).text() == "✓ Done"

        qv.clear()
        assert len(qv.get_items()) == 0
        assert qv._table.rowCount() == 0


# ---------------------------------------------------------------------------
# InstalledView tests
# ---------------------------------------------------------------------------


class TestInstalledView:
    def test_reload_and_filter(self, qapp, service: AppService, tmp_root: Path):
        service._registry.add_app(
            AppRecord(name="alpha", display_name="Alpha", format="appimage", version="1.0")
        )
        service._registry.add_app(
            AppRecord(name="beta", display_name="Beta", format="deb", version="2.0")
        )

        view = InstalledView(service)
        view.reload_data()
        assert view._table.rowCount() == 2

        # Filter by name
        view._search_input.setText("alp")
        assert view._table.rowCount() == 1
        assert view._table.item(0, 0).text() == "Alpha"

        # Clear filter
        view._search_input.setText("")
        assert view._table.rowCount() == 2

    def test_selection_enables_actions(self, qapp, service: AppService):
        app_id = service._registry.add_app(
            AppRecord(name="gamma", display_name="Gamma", format="appimage", version="1.0")
        )
        # Add backup to enable rollback
        service._registry.add_version(
            VersionRecord(
                app_id=app_id,
                version="0.9",
                backup_path="/tmp/fake_backup.AppImage",
                action="update",
            )
        )

        view = InstalledView(service)
        view.reload_data()

        assert not view._uninstall_btn.isEnabled()
        assert not view._rollback_btn.isEnabled()

        # Select row
        view._table.selectRow(0)
        assert view._uninstall_btn.isEnabled()
        assert view._history_btn.isEnabled()
        assert view._rollback_btn.isEnabled()


# ---------------------------------------------------------------------------
# Dialogs tests
# ---------------------------------------------------------------------------


class TestDialogs:
    def test_confirm_dialog_layout(self, qapp, tmp_path: Path):
        deb_info = PackageInfo(
            filepath=tmp_path / "pkg.deb",
            format=PackageFormat.DEB,
            name="pkg",
            version="1.0",
        )
        appimage_info = PackageInfo(
            filepath=tmp_path / "app.AppImage",
            format=PackageFormat.APPIMAGE,
            name="app",
            version="2.0",
        )
        items = [
            QueueItem(info=deb_info, action=DropAction.INSTALL),
            QueueItem(info=appimage_info, action=DropAction.UPDATE, existing_version="1.0"),
        ]

        dlg = ConfirmDialog(items)
        assert dlg is not None

    def test_history_dialog_layout(self, qapp):
        history = [
            VersionRecord(
                app_id=1,
                version="1.0",
                action="install",
                created_at="2026-10-20T10:00:00",
                notes="Initial install",
            ),
            VersionRecord(
                app_id=1,
                version="2.0",
                action="update",
                created_at="2026-10-20T11:00:00",
                notes="Update from 1.0",
            ),
        ]
        dlg = HistoryDialog("TestApp", history)
        assert dlg is not None

    def test_error_dialog(self, qapp):
        dlg = ErrorDialog("Error Title", "Something went wrong", "Detailed traceback")
        assert dlg is not None


# ---------------------------------------------------------------------------
# MainWindow tests
# ---------------------------------------------------------------------------


class TestMainWindow:
    def test_init_and_tabs(self, qapp, service: AppService):
        win = MainWindow(service=service)
        assert win.windowTitle() == "AppDrop"
        assert win._tabs.count() == 2

        # Switch to Installed Apps tab
        win._tabs.setCurrentIndex(1)
        assert win._tabs.currentIndex() == 1
