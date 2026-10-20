"""Tests for enhanced functionality: CLI arguments, SHA-256, dependencies, icons, launching, and backup retention."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from droppack.__main__ import main
from droppack.backends.appimage import AppImageBackend
from droppack.desktop import install_icon_bytes
from droppack.detect import PackageFormat, PackageInfo, detect
from droppack.gui.drop_zone import DropZone
from droppack.gui.installed_view import InstalledView
from droppack.gui.main_window import MainWindow
from droppack.registry import AppRecord, Registry, VersionRecord
from droppack.service import AppService


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _make_appimage(path: Path) -> Path:
    header = b"\x7fELF" + b"\x00" * 4 + b"AI\x02" + b"\x00" * 100
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header)
    return path


def _make_deb_with_deps(path: Path, name: str = "pkg", deps: str = "libc6 (>= 2.34), python3") -> Path:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pkg"
        (root / "DEBIAN").mkdir(parents=True)
        (root / "DEBIAN" / "control").write_text(
            f"Package: {name}\nVersion: 1.0\nArchitecture: all\n"
            f"Maintainer: Test <test@example.com>\nDepends: {deps}\n"
            f"Description: A test package\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["dpkg-deb", "-b", str(root), str(path)], check=True, capture_output=True)
    return path


class TestCLIAndArguments:
    def test_version_flag(self, capsys):
        ret = main(["--version"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "DropPack 0.1.0" in captured.out

    def test_help_flag(self, capsys):
        ret = main(["--help"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "Usage: droppack" in captured.out

    def test_main_window_loads_initial_files(self, qapp, tmp_root: Path, tmp_path: Path):
        f = _make_appimage(tmp_path / "App-1.0.AppImage")
        svc = AppService(root_override=tmp_root)
        try:
            win = MainWindow(service=svc, initial_files=[f])
            items = win._queue_view.get_items()
            assert len(items) == 1
            assert items[0].info.name == "App"
        finally:
            svc.close()


class TestSHA256AndDependencies:
    def test_sha256_computed(self, tmp_path: Path):
        test_file = tmp_path / "sample.deb"
        _make_deb_with_deps(test_file)
        info = detect(test_file)
        assert info.sha256 is not None
        assert len(info.sha256) == 64  # valid 64-character hex

    def test_deb_dependencies_extracted(self, tmp_path: Path):
        test_file = tmp_path / "sample.deb"
        _make_deb_with_deps(test_file, deps="libc6 (>= 2.34), python3, curl")
        info = detect(test_file)
        assert "libc6 (>= 2.34)" in info.dependencies
        assert "python3" in info.dependencies
        assert "curl" in info.dependencies


class TestIconBytesInstallation:
    def test_install_icon_bytes(self, tmp_root: Path):
        fake_icon = b"\x89PNG\r\n\x1a\nfake-png-data"
        dest = install_icon_bytes(fake_icon, "png", "testapp", root_override=tmp_root)
        assert dest.exists()
        assert dest.read_bytes() == fake_icon
        assert dest.name == "testapp.png"


class TestBackupRetention:
    def test_clean_old_backups(self, tmp_root: Path):
        reg = Registry(root_override=tmp_root)
        reg.open()
        try:
            app_id = reg.add_app(AppRecord(name="app", format="appimage", version="3.0"))

            # Create 3 backup files
            b1 = tmp_root / "backup1.AppImage"
            b2 = tmp_root / "backup2.AppImage"
            b3 = tmp_root / "backup3.AppImage"
            for b in (b1, b2, b3):
                b.touch()

            # Add in chronological order
            reg.add_version(VersionRecord(app_id=app_id, version="1.0", backup_path=str(b1), action="update"))
            reg.add_version(VersionRecord(app_id=app_id, version="2.0", backup_path=str(b2), action="update"))
            reg.add_version(VersionRecord(app_id=app_id, version="3.0", backup_path=str(b3), action="update"))

            backend = AppImageBackend(reg, root_override=tmp_root)
            # Keep only the latest 1 backup
            deleted = backend.clean_old_backups(app_id, keep_count=1)

            assert deleted == 2
            # Most recent (b3) should exist, older ones removed
            assert b3.exists()
            assert not b1.exists()
            assert not b2.exists()
        finally:
            reg.close()


class TestApplicationLaunch:
    def test_launch_appimage(self, tmp_root: Path, tmp_path: Path):
        app_file = tmp_path / "executable.AppImage"
        app_file.touch()

        reg = Registry(root_override=tmp_root)
        reg.open()
        try:
            app_id = reg.add_app(
                AppRecord(
                    name="launchme",
                    format="appimage",
                    install_path=str(app_file),
                    status="installed",
                )
            )

            svc = AppService(root_override=tmp_root)
            try:
                with patch("subprocess.Popen") as mock_popen:
                    mock_popen.return_value = MagicMock()
                    success, err = svc.launch(app_id)
                    assert success
                    assert err is None
                    mock_popen.assert_called_once()
                    assert str(app_file) in mock_popen.call_args[0][0]
            finally:
                svc.close()
        finally:
            reg.close()

    def test_launch_nonexistent_fails(self, tmp_root: Path):
        svc = AppService(root_override=tmp_root)
        try:
            success, err = svc.launch(99999)
            assert not success
            assert "not found" in (err or "").lower()
        finally:
            svc.close()


class TestGUIEnhancements:
    def test_drop_zone_has_browse_button(self, qapp):
        dz = DropZone()
        assert hasattr(dz, "_browse_btn")
        assert dz._browse_btn.text() == "Browse Files…"

    def test_installed_view_has_launch_button(self, qapp, tmp_root: Path):
        svc = AppService(root_override=tmp_root)
        try:
            view = InstalledView(svc)
            assert hasattr(view, "_launch_btn")
            assert view._launch_btn.text() == "Launch"
        finally:
            svc.close()
