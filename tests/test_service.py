"""Tests for appdrop.service — orchestration layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from appdrop.detect import PackageFormat
from appdrop.service import AppService, DropAction, QueueItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deb(path: Path) -> Path:
    path.write_bytes(b"!<arch>\n" + b"\x00" * 100)
    return path


def _make_appimage(path: Path) -> Path:
    header = b"\x7fELF" + b"\x00" * 4 + b"AI\x02" + b"\x00" * 100
    path.write_bytes(header)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProcessFiles:
    def test_single_deb(self, tmp_path: Path):
        f = _make_deb(tmp_path / "pkg.deb")
        svc = AppService()
        items = svc.process_files([f])
        assert len(items) == 1
        assert items[0].info.format == PackageFormat.DEB
        assert items[0].action == DropAction.INSTALL

    def test_single_appimage(self, tmp_path: Path):
        f = _make_appimage(tmp_path / "App-1.0-x86_64.AppImage")
        svc = AppService()
        items = svc.process_files([f])
        assert len(items) == 1
        assert items[0].info.format == PackageFormat.APPIMAGE
        assert items[0].action == DropAction.INSTALL

    def test_multiple_files(self, tmp_path: Path):
        files = [
            _make_deb(tmp_path / "a.deb"),
            _make_appimage(tmp_path / "B-2.0-x86_64.AppImage"),
            _make_deb(tmp_path / "c.deb"),
        ]
        svc = AppService()
        items = svc.process_files(files)
        assert len(items) == 3

    def test_unknown_file(self, tmp_path: Path):
        f = tmp_path / "garbage.txt"
        f.write_bytes(b"not a package")
        svc = AppService()
        items = svc.process_files([f])
        assert len(items) == 1
        assert items[0].action == DropAction.UNKNOWN
        assert not items[0].can_proceed

    def test_missing_file(self, tmp_path: Path):
        svc = AppService()
        items = svc.process_files([tmp_path / "missing.deb"])
        assert len(items) == 1
        assert items[0].info.error is not None
        assert not items[0].can_proceed

    def test_empty_list(self):
        svc = AppService()
        items = svc.process_files([])
        assert items == []


class TestExecuteQueue:
    def test_not_implemented(self, tmp_path: Path):
        f = _make_deb(tmp_path / "pkg.deb")
        svc = AppService()
        items = svc.process_files([f])
        with pytest.raises(NotImplementedError):
            svc.execute_queue(items)


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
