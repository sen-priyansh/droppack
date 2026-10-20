"""Application configuration, XDG path resolution, and logging setup.

All managed paths live under an ``droppack`` subdirectory inside standard
XDG base directories.  Every path helper accepts an optional *root_override*
so that tests can redirect I/O to a temporary directory.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

APP_NAME = "droppack"

# ---------------------------------------------------------------------------
# XDG path helpers
# ---------------------------------------------------------------------------

def _xdg_dir(env_var: str, fallback_suffix: str, root_override: Path | None = None) -> Path:
    """Return an XDG base directory, optionally relocated under *root_override*.

    When *root_override* is given the returned path is
    ``root_override / fallback_suffix / APP_NAME`` which keeps the layout
    predictable in tests without polluting the real home directory.
    """
    if root_override is not None:
        return root_override / fallback_suffix / APP_NAME
    base = os.environ.get(env_var)
    if base:
        return Path(base) / APP_NAME
    return Path.home() / fallback_suffix / APP_NAME


def data_dir(root_override: Path | None = None) -> Path:
    """``$XDG_DATA_HOME/droppack`` — registry, installed AppImages, backups."""
    return _xdg_dir("XDG_DATA_HOME", ".local/share", root_override)


def config_dir(root_override: Path | None = None) -> Path:
    """``$XDG_CONFIG_HOME/droppack`` — user preferences (future)."""
    return _xdg_dir("XDG_CONFIG_HOME", ".config", root_override)


def cache_dir(root_override: Path | None = None) -> Path:
    """``$XDG_CACHE_HOME/droppack`` — temporary staging area."""
    return _xdg_dir("XDG_CACHE_HOME", ".cache", root_override)


def log_dir(root_override: Path | None = None) -> Path:
    """Directory for log files, under the data directory."""
    return data_dir(root_override) / "logs"


# ---------------------------------------------------------------------------
# Managed sub-directories inside data_dir
# ---------------------------------------------------------------------------

def apps_dir(root_override: Path | None = None) -> Path:
    """Where installed AppImages are stored."""
    return data_dir(root_override) / "apps"


def backups_dir(root_override: Path | None = None) -> Path:
    """Where previous AppImage versions are kept for rollback."""
    return data_dir(root_override) / "backups"


def registry_path(root_override: Path | None = None) -> Path:
    """Full path to the SQLite registry database."""
    return data_dir(root_override) / "registry.db"


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------

_MANAGED_DIRS = (data_dir, config_dir, cache_dir, log_dir, apps_dir, backups_dir)


def ensure_dirs(root_override: Path | None = None) -> list[Path]:
    """Create all managed directories if they do not exist.

    Returns the list of directories that were created or already existed.
    """
    dirs: list[Path] = []
    for dir_fn in _MANAGED_DIRS:
        d = dir_fn(root_override)
        d.mkdir(parents=True, exist_ok=True)
        dirs.append(d)
    return dirs


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    *,
    root_override: Path | None = None,
    level: int = logging.INFO,
    log_to_file: bool = True,
) -> logging.Logger:
    """Configure the root ``droppack`` logger.

    * Always logs to stderr.
    * Optionally logs to a file inside :func:`log_dir`.

    Returns the configured logger.
    """
    logger = logging.getLogger(APP_NAME)
    # Avoid duplicate handlers if called more than once.
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (optional)
    if log_to_file:
        ld = log_dir(root_override)
        ld.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(ld / "droppack.log", encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger
