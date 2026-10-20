"""Tests for appdrop.config — paths, directory creation, and logging."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import appdrop
from appdrop.config import (
    APP_NAME,
    apps_dir,
    backups_dir,
    cache_dir,
    config_dir,
    data_dir,
    ensure_dirs,
    log_dir,
    registry_path,
    setup_logging,
)


# ── Path resolution ────────────────────────────────────────────────────────

class TestDefaultPaths:
    """Verify XDG-based path resolution with no root override."""

    def test_data_dir_ends_with_appname(self):
        assert data_dir().name == APP_NAME

    def test_config_dir_ends_with_appname(self):
        assert config_dir().name == APP_NAME

    def test_cache_dir_ends_with_appname(self):
        assert cache_dir().name == APP_NAME

    def test_log_dir_inside_data(self):
        assert log_dir().parent == data_dir()

    def test_apps_dir_inside_data(self):
        assert apps_dir().parent == data_dir()

    def test_backups_dir_inside_data(self):
        assert backups_dir().parent == data_dir()

    def test_registry_path_inside_data(self):
        assert registry_path().parent == data_dir()
        assert registry_path().name == "registry.db"

    def test_default_paths_are_absolute(self):
        for fn in (data_dir, config_dir, cache_dir, log_dir, apps_dir, backups_dir, registry_path):
            assert fn().is_absolute(), f"{fn.__name__}() is not absolute"


class TestCustomPaths:
    """Verify paths can be relocated under a custom root (for testing)."""

    def test_data_dir_relocated(self, tmp_root: Path):
        d = data_dir(root_override=tmp_root)
        assert str(d).startswith(str(tmp_root))
        assert d.name == APP_NAME

    def test_cache_dir_relocated(self, tmp_root: Path):
        d = cache_dir(root_override=tmp_root)
        assert str(d).startswith(str(tmp_root))
        assert d.name == APP_NAME

    def test_config_dir_relocated(self, tmp_root: Path):
        d = config_dir(root_override=tmp_root)
        assert str(d).startswith(str(tmp_root))
        assert d.name == APP_NAME

    def test_log_dir_relocated(self, tmp_root: Path):
        d = log_dir(root_override=tmp_root)
        assert str(d).startswith(str(tmp_root))

    def test_registry_relocated(self, tmp_root: Path):
        p = registry_path(root_override=tmp_root)
        assert str(p).startswith(str(tmp_root))

    def test_overridden_paths_do_not_touch_home(self, tmp_root: Path):
        home = str(Path.home())
        for fn in (data_dir, config_dir, cache_dir, log_dir, apps_dir, backups_dir, registry_path):
            assert not str(fn(root_override=tmp_root)).startswith(home)


class TestXDGEnvOverride:
    """Verify that XDG environment variables are respected."""

    def test_xdg_data_home(self, tmp_root: Path, monkeypatch):
        custom = tmp_root / "custom_data"
        monkeypatch.setenv("XDG_DATA_HOME", str(custom))
        d = data_dir()  # no root_override — should use env
        assert str(d).startswith(str(custom))

    def test_root_override_takes_precedence(self, tmp_root: Path, monkeypatch):
        """root_override should win over env variables."""
        monkeypatch.setenv("XDG_DATA_HOME", "/should/not/use/this")
        d = data_dir(root_override=tmp_root)
        assert str(d).startswith(str(tmp_root))


# ── Directory creation ─────────────────────────────────────────────────────

class TestEnsureDirs:
    def test_creates_all_managed_dirs(self, tmp_root: Path):
        dirs = ensure_dirs(root_override=tmp_root)
        assert len(dirs) >= 5  # data, config, cache, log, apps, backups
        for d in dirs:
            assert d.is_dir(), f"{d} was not created"

    def test_idempotent(self, tmp_root: Path):
        ensure_dirs(root_override=tmp_root)
        # Calling again should not raise
        dirs = ensure_dirs(root_override=tmp_root)
        for d in dirs:
            assert d.is_dir()


# ── Logging ────────────────────────────────────────────────────────────────

class TestLogging:
    def test_setup_returns_logger(self, tmp_root: Path):
        logger = setup_logging(root_override=tmp_root)
        assert isinstance(logger, logging.Logger)
        assert logger.name == APP_NAME

    def test_log_file_created(self, tmp_root: Path):
        logger = setup_logging(root_override=tmp_root)
        logger.info("test message")
        log_file = log_dir(tmp_root) / "appdrop.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "test message" in content

    def test_no_duplicate_handlers(self, tmp_root: Path):
        logger = setup_logging(root_override=tmp_root)
        handler_count = len(logger.handlers)
        setup_logging(root_override=tmp_root)
        assert len(logger.handlers) == handler_count

    def test_file_logging_optional(self, tmp_root: Path):
        logger = setup_logging(root_override=tmp_root, log_to_file=False)
        # Should only have the console handler
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 0


# ── Version ────────────────────────────────────────────────────────────────

class TestVersion:
    def test_version_is_string(self):
        assert isinstance(appdrop.__version__, str)

    def test_version_is_semver(self):
        # Loose semver: major.minor.patch with optional pre-release
        assert re.match(r"^\d+\.\d+\.\d+", appdrop.__version__)
