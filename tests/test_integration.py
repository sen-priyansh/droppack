"""End-to-end integration tests and security verification."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from droppack.backends.appimage import AppImageBackend
from droppack.backends.deb import DebBackend
from droppack.config import apps_dir, backups_dir
from droppack.detect import PackageFormat, PackageInfo, detect
from droppack.identity import IdentityResolver
from droppack.registry import Registry
from droppack.service import AppService, DropAction


def _make_appimage(path: Path, version: str = "1.0", payload: bytes = b"binary-content") -> Path:
    header = b"\x7fELF" + b"\x00" * 4 + b"AI\x02" + b"\x00" * 100
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + payload)
    return path


def _make_deb(path: Path, name: str, version: str) -> Path:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pkg"
        (root / "DEBIAN").mkdir(parents=True)
        (root / "DEBIAN" / "control").write_text(
            f"Package: {name}\nVersion: {version}\nArchitecture: all\n"
            f"Maintainer: Test <test@example.com>\nDescription: Test package\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["dpkg-deb", "-b", str(root), str(path)], check=True, capture_output=True)
    return path


# ---------------------------------------------------------------------------
# E2E AppImage Lifecycle Test
# ---------------------------------------------------------------------------


class TestAppImageLifecycleE2E:
    def test_full_appimage_lifecycle(self, tmp_root: Path, tmp_path: Path):
        """Test complete lifecycle: Install -> Update -> Rollback -> Uninstall."""
        svc = AppService(root_override=tmp_root)
        try:
            # 1. New installation (v1.0)
            v1_file = _make_appimage(tmp_path / "SuperTool-1.0-x86_64.AppImage", "1.0", b"v1")
            items = svc.process_files([v1_file])
            assert len(items) == 1
            assert items[0].action == DropAction.INSTALL
            assert items[0].can_proceed

            res1 = svc.execute_queue(items)
            assert res1[0].info.error is None

            # Verify installed
            installed = svc.list_installed()
            assert len(installed) == 1
            app = installed[0]
            assert app.name == "SuperTool"
            assert app.version == "1.0"
            assert Path(app.install_path).exists()
            assert Path(app.desktop_entry).exists()

            # 2. Update to v2.0
            v2_file = _make_appimage(tmp_path / "SuperTool-2.0-x86_64.AppImage", "2.0", b"v2")
            items2 = svc.process_files([v2_file])
            assert len(items2) == 1
            assert items2[0].action == DropAction.UPDATE
            assert items2[0].existing_version == "1.0"

            res2 = svc.execute_queue(items2)
            assert res2[0].info.error is None

            # Verify updated
            app = svc._registry.get_app(app.id)
            assert app.version == "2.0"
            history = svc.get_version_history(app.id)
            assert len(history) == 2
            assert history[0].action == "update"
            assert history[0].backup_path is not None
            assert Path(history[0].backup_path).exists()

            # 3. Rollback to v1.0
            rb_result = svc.rollback(app.id)
            assert rb_result.success
            app = svc._registry.get_app(app.id)
            assert app.version == "1.0"

            history_rb = svc.get_version_history(app.id)
            assert len(history_rb) == 3
            assert history_rb[0].action == "rollback"

            # 4. Uninstall
            un_result = svc.uninstall(app.id)
            assert un_result.success
            assert not Path(app.install_path).exists()
            assert not Path(app.desktop_entry).exists()

            # Verify marked removed
            assert len(svc.list_installed()) == 0
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# Corrupt files and edge cases
# ---------------------------------------------------------------------------


class TestEdgeCasesAndCorruptFiles:
    def test_corrupt_file_handling(self, tmp_root: Path, tmp_path: Path):
        svc = AppService(root_override=tmp_root)
        try:
            # File that is not ELF and not Debian ar
            bad_file = tmp_path / "corrupt.deb"
            bad_file.write_bytes(b"THIS IS CORRUPTED DATA")

            items = svc.process_files([bad_file])
            assert len(items) == 1
            assert items[0].action == DropAction.UNKNOWN
            assert not items[0].can_proceed
            assert items[0].info.error is not None
        finally:
            svc.close()

    def test_nonexistent_file(self, tmp_root: Path, tmp_path: Path):
        svc = AppService(root_override=tmp_root)
        try:
            items = svc.process_files([tmp_path / "ghost.AppImage"])
            assert len(items) == 1
            assert not items[0].can_proceed
        finally:
            svc.close()

    def test_empty_appimage(self, tmp_root: Path, tmp_path: Path):
        svc = AppService(root_override=tmp_root)
        try:
            empty = tmp_path / "empty.AppImage"
            empty.write_bytes(b"")
            items = svc.process_files([empty])
            assert not items[0].can_proceed
        finally:
            svc.close()


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------


class TestSecurityAudit:
    def test_droppack_deb_package_inspection(self):
        """Verify DropPack's own built Debian package can be inspected correctly."""
        deb_path = Path(__file__).resolve().parent.parent / "dist" / "droppack_0.1.0_all.deb"
        if not deb_path.exists():
            from scripts.build_deb import build_deb
            deb_path = build_deb()

        info = detect(deb_path)
        assert info.format == PackageFormat.DEB
        assert info.name == "droppack"
        assert info.version == "0.1.0"
        assert info.architecture == "all"
        assert info.error is None

    def test_no_shell_true_in_source_tree(self):
        """Ensure shell=True is never used anywhere in the codebase."""
        src_dir = Path(__file__).resolve().parent.parent / "src"
        matches = []
        for py_file in src_dir.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            if "shell=True" in text:
                matches.append(str(py_file))
        assert matches == [], f"Found shell=True in: {matches}"

    def test_path_traversal_sanitisation(self, tmp_root: Path):
        from droppack.desktop import _sanitise
        # Characters like ../, ;, |, &, $, ` must be sanitised
        assert ".." not in _sanitise("../../etc/passwd")
        assert ";" not in _sanitise("my; rm -rf /")
        assert "&" not in _sanitise("app&echo hello")
        assert "`" not in _sanitise("app`calc`")

    def test_appimage_outside_directory_safety(self, tmp_root: Path):
        """Refuse to delete files outside the managed directory."""
        reg = Registry(root_override=tmp_root)
        reg.open()
        try:
            from droppack.registry import AppRecord
            system_file = tmp_root / "system_important_file"
            system_file.write_text("critical")

            rec = AppRecord(
                name="fake",
                format="appimage",
                install_path=str(system_file),
                status="installed",
            )
            app_id = reg.add_app(rec)

            backend = AppImageBackend(reg, root_override=tmp_root)
            result = backend.uninstall(app_id)
            assert not result.success
            assert "outside" in (result.error or "").lower()
            # File must still exist
            assert system_file.exists()
        finally:
            reg.close()
