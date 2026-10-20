"""Tests for appdrop.registry — SQLite-backed application registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from appdrop.registry import AppRecord, Registry, VersionRecord


@pytest.fixture()
def registry(tmp_root: Path) -> Registry:
    reg = Registry(root_override=tmp_root)
    reg.open()
    yield reg
    reg.close()


def _sample_app(**overrides) -> AppRecord:
    defaults = dict(
        name="test-app",
        display_name="Test App",
        format="appimage",
        version="1.0.0",
        architecture="x86_64",
        description="A test application",
        install_path="/tmp/apps/test.AppImage",
        status="installed",
    )
    defaults.update(overrides)
    return AppRecord(**defaults)


# ---------------------------------------------------------------------------
# Schema and connection
# ---------------------------------------------------------------------------


class TestConnection:
    def test_open_creates_db(self, tmp_root: Path):
        reg = Registry(root_override=tmp_root)
        reg.open()
        from appdrop.config import registry_path
        assert registry_path(tmp_root).exists()
        reg.close()

    def test_operations_fail_before_open(self, tmp_root: Path):
        reg = Registry(root_override=tmp_root)
        with pytest.raises(RuntimeError, match="not open"):
            reg.add_app(_sample_app())

    def test_close_is_idempotent(self, tmp_root: Path):
        reg = Registry(root_override=tmp_root)
        reg.open()
        reg.close()
        reg.close()  # should not raise


# ---------------------------------------------------------------------------
# App CRUD
# ---------------------------------------------------------------------------


class TestAppCRUD:
    def test_add_and_get(self, registry: Registry):
        rec = _sample_app()
        app_id = registry.add_app(rec)
        assert app_id > 0

        fetched = registry.get_app(app_id)
        assert fetched is not None
        assert fetched.name == "test-app"
        assert fetched.version == "1.0.0"

    def test_add_sets_timestamps(self, registry: Registry):
        rec = _sample_app()
        registry.add_app(rec)
        assert rec.installed_at != ""
        assert rec.updated_at != ""

    def test_find_app(self, registry: Registry):
        registry.add_app(_sample_app(name="foo", format="appimage"))
        result = registry.find_app("foo", "appimage")
        assert result is not None
        assert result.name == "foo"

    def test_find_app_not_found(self, registry: Registry):
        assert registry.find_app("nope", "appimage") is None

    def test_update_app(self, registry: Registry):
        rec = _sample_app()
        app_id = registry.add_app(rec)

        rec.version = "2.0.0"
        registry.update_app(rec)

        fetched = registry.get_app(app_id)
        assert fetched is not None
        assert fetched.version == "2.0.0"

    def test_list_apps(self, registry: Registry):
        registry.add_app(_sample_app(name="alpha"))
        registry.add_app(_sample_app(name="beta"))
        apps = registry.list_apps()
        assert len(apps) == 2
        names = [a.name for a in apps]
        assert "alpha" in names
        assert "beta" in names

    def test_remove_app_soft_delete(self, registry: Registry):
        rec = _sample_app()
        app_id = registry.add_app(rec)
        registry.remove_app(app_id)

        # Should not appear in default listing
        assert len(registry.list_apps()) == 0

        # But still retrievable directly
        fetched = registry.get_app(app_id)
        assert fetched is not None
        assert fetched.status == "removed"

    def test_delete_app_hard(self, registry: Registry):
        rec = _sample_app()
        app_id = registry.add_app(rec)
        registry.delete_app(app_id)
        assert registry.get_app(app_id) is None

    def test_unique_constraint(self, registry: Registry):
        registry.add_app(_sample_app(name="dup", format="appimage"))
        with pytest.raises(Exception):
            registry.add_app(_sample_app(name="dup", format="appimage"))


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


class TestVersionHistory:
    def test_add_and_get_versions(self, registry: Registry):
        app_id = registry.add_app(_sample_app())
        registry.add_version(VersionRecord(
            app_id=app_id, version="1.0.0", action="install",
        ))
        registry.add_version(VersionRecord(
            app_id=app_id, version="2.0.0", action="update",
            backup_path="/tmp/backup.AppImage",
        ))

        versions = registry.get_versions(app_id)
        assert len(versions) == 2
        # Most recent first
        assert versions[0].version == "2.0.0"

    def test_get_latest_backup(self, registry: Registry):
        app_id = registry.add_app(_sample_app())
        registry.add_version(VersionRecord(
            app_id=app_id, version="1.0", action="install",
        ))
        registry.add_version(VersionRecord(
            app_id=app_id, version="2.0", action="update",
            backup_path="/tmp/backup-v1.AppImage",
        ))

        backup = registry.get_latest_backup(app_id)
        assert backup is not None
        assert backup.version == "2.0"
        assert backup.backup_path == "/tmp/backup-v1.AppImage"

    def test_no_backup_returns_none(self, registry: Registry):
        app_id = registry.add_app(_sample_app())
        registry.add_version(VersionRecord(
            app_id=app_id, version="1.0", action="install",
        ))
        assert registry.get_latest_backup(app_id) is None
