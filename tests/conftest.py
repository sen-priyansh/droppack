"""Shared pytest fixtures for DropPack tests."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    """Provide a temporary root directory that replaces $HOME for path helpers.

    Every config function that accepts ``root_override`` can use this so that
    tests never touch the real home directory.
    """
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_logger():
    """Remove handlers from the droppack logger between tests.

    This prevents ``setup_logging`` from thinking it has already been
    configured and skipping handler creation.
    """
    logger = logging.getLogger("droppack")
    yield
    logger.handlers.clear()
    logger.setLevel(logging.WARNING)
