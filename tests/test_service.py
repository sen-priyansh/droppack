"""Tests for appdrop.service — orchestration layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from appdrop.detect import PackageFormat
from appdrop.service import AppService, DropAction, QueueItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deb(path: Path, name: str = "pkg", version: str = "1.0", arch: str = "all") -> Path:
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pkg"
        (root / "DEBIAN").mkdir(parents=True)
        (root / "DEBIAN" / "control").write_text(
            f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\nMaintainer: Test <test@example.com>\nDescription: Test package\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["dpkg-deb", "-b", str(root), str(path)], check=True, capture_output=True)
    return path


def _make_appimage(path: Path, content: bytes = b"") -> Path:
    header = b"\x7fELF" + b"\x00" * 4 + b"AI\x02" + b"\x00" * 100
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + content)
    return path


@pytest.fixture()
def service(tmp_root: Path):
    svc = AppService(root_override=tmp_root)
    yield svc
    svc.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProcessFiles:
    def test_single_deb(self, service: AppService, tmp_path: Path):
        f = _make_deb(tmp_path / "pkg.deb")
        items = service.process_files([f])
        assert len(items) == 1
        assert items[0].info.format == PackageFormat.DEB
        assert items[0].action == DropAction.INSTALL

    def test_single_appimage(self, service: AppService, tmp_path: Path):
        f = _make_appimage(tmp_path / "App-1.0-x86_64.AppImage")
        items = service.process_files([f])
        assert len(items) == 1
        assert items[0].info.format == PackageFormat.APPIMAGE
        assert items[0].action == DropAction.INSTALL

    def test_multiple_files(self, service: AppService, tmp_path: Path):
        files = [
            _make_deb(tmp_path / "a.deb"),
            _make_appimage(tmp_path / "B-2.0-x86_64.AppImage"),
            _make_deb(tmp_path / "c.deb"),
        ]
        items = service.process_files(files)
        assert len(items) == 3

    def test_unknown_file(self, service: AppService, tmp_path: Path):
        f = tmp_path / "garbage.txt"
        f.write_bytes(b"not a package")
        items = service.process_files([f])
        assert len(items) == 1
        assert items[0].action == DropAction.UNKNOWN
        assert not items[0].can_proceed

    def test_missing_file(self, service: AppService, tmp_path: Path):
        items = service.process_files([tmp_path / "missing.deb"])
        assert len(items) == 1
        assert items[0].info.error is not None
        assert not items[0].can_proceed

    def test_empty_list(self, service: AppService):
        items = service.process_files([])
        assert items == []


class TestIdentityIntegration:
    def test_detects_update(self, service: AppService, tmp_path: Path):
        # Install first
        src1 = _make_appimage(tmp_path / "App-1.0-x86_64.AppImage", b"v1")
        items1 = service.process_files([src1])
        service.execute_queue(items1)

        # Drop again — should detect as update
        src2 = _make_appimage(tmp_path / "v2" / "App-2.0-x86_64.AppImage", b"v2")
        items2 = service.process_files([src2])
        assert items2[0].action == DropAction.UPDATE

    def test_new_app_is_install(self, service: AppService, tmp_path: Path):
        src = _make_appimage(tmp_path / "Brand-New-1.0.AppImage")
        items = service.process_files([src])
        assert items[0].action == DropAction.INSTALL


class TestExecuteQueue:
    def test_appimage_install(self, service: AppService, tmp_path: Path):
        src = _make_appimage(tmp_path / "App-1.0.AppImage")
        items = service.process_files([src])
        results = service.execute_queue(items)
        assert results[0].info.error is None

        installed = service.list_installed()
        assert len(installed) >= 1

    def test_deb_not_yet_implemented(self, service: AppService, tmp_path: Path):
        src = _make_deb(tmp_path / "pkg.deb")
        items = service.process_files([src])
        results = service.execute_queue(items)
        assert results[0].info.error is not None
        assert "not yet implemented" in results[0].info.error.lower()


class TestManagement:
    def test_uninstall(self, service: AppService, tmp_path: Path):
        src = _make_appimage(tmp_path / "App.AppImage")
        items = service.process_files([src])
        service.execute_queue(items)

        installed = service.list_installed()
        assert len(installed) == 1

        result = service.uninstall(installed[0].id)
        assert result.success

    def test_rollback_no_backup(self, service: AppService, tmp_path: Path):
        src = _make_appimage(tmp_path / "App.AppImage")
        items = service.process_files([src])
        service.execute_queue(items)

        installed = service.list_installed()
        result = service.rollback(installed[0].id)
        assert not result.success

    def test_version_history(self, service: AppService, tmp_path: Path):
        src = _make_appimage(tmp_path / "App.AppImage")
        items = service.process_files([src])
        service.execute_queue(items)

        installed = service.list_installed()
        history = service.get_version_history(installed[0].id)
        assert len(history) >= 1


class TestQueueItem:
    def test_can_proceed_true(self, tmp_path: Path):
        from appdrop.detect import PackageInfo
        info = PackageInfo(filepath=tmp_path / "a.deb", format=PackageFormat.DEB)
        item = QueueItem(info=info, action=DropAction.INSTALL)
        assert item.can_proceed

    def test_can_proceed_false_on_error(self, tmp_path: Path):
        from appdrop.detect import PackageInfo
        info = PackageInfo(
            filepath=tmp_path / "a.deb",
            format=PackageFormat.DEB,
            error="something broke",
        )
        item = QueueItem(info=info, action=DropAction.INSTALL)
        assert not item.can_proceed

    def test_can_proceed_false_on_unknown(self, tmp_path: Path):
        from appdrop.detect import PackageInfo
        info = PackageInfo(filepath=tmp_path / "x.bin", format=PackageFormat.UNKNOWN)
        item = QueueItem(info=info, action=DropAction.UNKNOWN)
        assert not item.can_proceed

    def test_display_action_update(self, tmp_path: Path):
        from appdrop.detect import PackageInfo
        info = PackageInfo(filepath=tmp_path / "a.AppImage", format=PackageFormat.APPIMAGE, version="2.0")
        item = QueueItem(info=info, action=DropAction.UPDATE, existing_version="1.0")
        assert "1.0" in item.display_action
        assert "2.0" in item.display_action
