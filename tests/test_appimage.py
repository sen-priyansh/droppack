"""Tests for appdrop.backends.appimage — AppImage install, update, rollback, uninstall."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from appdrop.backends.appimage import AppImageBackend, InstallResult
from appdrop.config import apps_dir, backups_dir
from appdrop.detect import PackageFormat, PackageInfo
from appdrop.registry import AppRecord, Registry


@pytest.fixture()
def registry(tmp_root: Path) -> Registry:
    reg = Registry(root_override=tmp_root)
    reg.open()
    yield reg
    reg.close()


@pytest.fixture()
def backend(registry: Registry, tmp_root: Path) -> AppImageBackend:
    return AppImageBackend(registry, root_override=tmp_root)


def _make_fake_appimage(path: Path, content: bytes = b"\x7fELFfake") -> Path:
    """Create a fake AppImage file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _make_info(filepath: Path, name: str = "TestApp", version: str = "1.0") -> PackageInfo:
    return PackageInfo(
        filepath=filepath,
        format=PackageFormat.APPIMAGE,
        name=name,
        version=version,
        description="A test application",
        architecture="x86_64",
    )


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


class TestInstall:
    def test_basic_install(self, backend: AppImageBackend, tmp_root: Path, tmp_path: Path):
        src = _make_fake_appimage(tmp_path / "TestApp-1.0-x86_64.AppImage")
        info = _make_info(src)

        result = backend.install(info)

        assert result.success
        assert result.install_path is not None
        assert result.install_path.exists()
        assert result.desktop_entry is not None
        assert result.desktop_entry.exists()

    def test_installed_file_is_executable(self, backend: AppImageBackend, tmp_root: Path, tmp_path: Path):
        src = _make_fake_appimage(tmp_path / "App.AppImage")
        info = _make_info(src)

        result = backend.install(info)
        assert result.install_path is not None
        mode = result.install_path.stat().st_mode
        assert mode & stat.S_IXUSR

    def test_install_registers_in_db(self, backend: AppImageBackend, registry: Registry, tmp_path: Path):
        src = _make_fake_appimage(tmp_path / "App.AppImage")
        info = _make_info(src, name="RegApp")

        backend.install(info)

        app = registry.find_app("RegApp", "appimage")
        assert app is not None
        assert app.version == "1.0"

    def test_install_creates_version_history(self, backend: AppImageBackend, registry: Registry, tmp_path: Path):
        src = _make_fake_appimage(tmp_path / "App.AppImage")
        info = _make_info(src)

        backend.install(info)

        app = registry.find_app("TestApp", "appimage")
        assert app is not None
        versions = registry.get_versions(app.id)
        assert len(versions) == 1
        assert versions[0].action == "install"

    def test_install_duplicate_fails(self, backend: AppImageBackend, tmp_path: Path):
        src = _make_fake_appimage(tmp_path / "Dup.AppImage")
        info = _make_info(src, name="DupApp")

        result1 = backend.install(info)
        assert result1.success

        # Create a new source file with same name
        src2 = _make_fake_appimage(tmp_path / "Dup2" / "Dup.AppImage")
        info2 = _make_info(src2, name="DupApp")
        result2 = backend.install(info2)
        assert not result2.success
        assert "already exists" in (result2.error or "").lower()

    def test_install_nonexistent_source(self, backend: AppImageBackend, tmp_path: Path):
        info = _make_info(tmp_path / "missing.AppImage")
        result = backend.install(info)
        assert not result.success


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_basic_update(self, backend: AppImageBackend, registry: Registry, tmp_root: Path, tmp_path: Path):
        # Install v1
        src1 = _make_fake_appimage(tmp_path / "App.AppImage", b"\x7fELFv1")
        info1 = _make_info(src1, version="1.0")
        backend.install(info1)

        existing = registry.find_app("TestApp", "appimage")
        assert existing is not None

        # Update to v2
        src2 = _make_fake_appimage(tmp_path / "v2" / "App.AppImage", b"\x7fELFv2")
        info2 = _make_info(src2, version="2.0")
        result = backend.update(info2, existing)

        assert result.success
        assert result.install_path is not None

        # Verify version updated in registry
        updated = registry.get_app(existing.id)
        assert updated is not None
        assert updated.version == "2.0"

    def test_update_creates_backup(self, backend: AppImageBackend, registry: Registry, tmp_root: Path, tmp_path: Path):
        # Install v1
        src1 = _make_fake_appimage(tmp_path / "App.AppImage", b"\x7fELFv1")
        info1 = _make_info(src1, version="1.0")
        backend.install(info1)

        existing = registry.find_app("TestApp", "appimage")
        assert existing is not None

        # Update to v2
        src2 = _make_fake_appimage(tmp_path / "v2" / "App.AppImage", b"\x7fELFv2")
        info2 = _make_info(src2, version="2.0")
        backend.update(info2, existing)

        # Check backup exists
        backup = registry.get_latest_backup(existing.id)
        assert backup is not None
        assert backup.backup_path is not None
        assert Path(backup.backup_path).exists()


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


class TestRollback:
    def test_rollback_to_previous_version(self, backend: AppImageBackend, registry: Registry, tmp_root: Path, tmp_path: Path):
        # Install v1
        src1 = _make_fake_appimage(tmp_path / "App.AppImage", b"\x7fELFv1")
        info1 = _make_info(src1, version="1.0")
        backend.install(info1)

        existing = registry.find_app("TestApp", "appimage")
        assert existing is not None
        app_id = existing.id

        # Update to v2
        src2 = _make_fake_appimage(tmp_path / "v2" / "App.AppImage", b"\x7fELFv2")
        info2 = _make_info(src2, version="2.0")
        backend.update(info2, existing)

        # Rollback
        result = backend.rollback(app_id)
        assert result.success

        # Verify version reverted
        reverted = registry.get_app(app_id)
        assert reverted is not None
        assert reverted.version == "1.0"

    def test_rollback_no_backup(self, backend: AppImageBackend, registry: Registry, tmp_path: Path):
        src = _make_fake_appimage(tmp_path / "App.AppImage")
        info = _make_info(src)
        backend.install(info)

        existing = registry.find_app("TestApp", "appimage")
        result = backend.rollback(existing.id)
        assert not result.success
        assert "no backup" in (result.error or "").lower()

    def test_rollback_nonexistent_app(self, backend: AppImageBackend):
        result = backend.rollback(9999)
        assert not result.success


# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------


class TestUninstall:
    def test_basic_uninstall(self, backend: AppImageBackend, registry: Registry, tmp_root: Path, tmp_path: Path):
        src = _make_fake_appimage(tmp_path / "App.AppImage")
        info = _make_info(src)
        install_result = backend.install(info)

        existing = registry.find_app("TestApp", "appimage")
        assert existing is not None

        result = backend.uninstall(existing.id)
        assert result.success

        # File should be removed
        assert not install_result.install_path.exists()

        # App should be marked as removed
        app = registry.get_app(existing.id)
        assert app.status == "removed"

    def test_uninstall_nonexistent(self, backend: AppImageBackend):
        result = backend.uninstall(9999)
        assert not result.success

    def test_uninstall_outside_managed_dir(self, backend: AppImageBackend, registry: Registry, tmp_root: Path):
        """Verify safety check prevents deleting files outside managed dir."""
        rec = AppRecord(
            name="evil",
            format="appimage",
            install_path="/etc/passwd",
            status="installed",
        )
        app_id = registry.add_app(rec)
        result = backend.uninstall(app_id)
        assert not result.success
        assert "outside" in (result.error or "").lower()
