"""Tests for appdrop.desktop — .desktop file and icon management."""

from __future__ import annotations

from pathlib import Path

from appdrop.desktop import (
    _sanitise,
    applications_dir,
    create_desktop_entry,
    icons_dir,
    install_icon,
    remove_desktop_entry,
    remove_icon,
)


class TestSanitise:
    def test_simple_name(self):
        assert _sanitise("MyApp") == "myapp"

    def test_spaces(self):
        assert _sanitise("My App") == "my-app"

    def test_special_chars(self):
        assert _sanitise("app@v2!") == "app-v2"


class TestDesktopEntry:
    def test_creates_desktop_file(self, tmp_root: Path):
        exec_path = tmp_root / "app.AppImage"
        exec_path.touch()

        result = create_desktop_entry(
            app_name="Test App",
            exec_path=exec_path,
            root_override=tmp_root,
        )

        assert result.exists()
        assert result.suffix == ".desktop"

        content = result.read_text()
        assert "Name=Test App" in content
        assert str(exec_path) in content
        assert "X-AppDrop-Managed=true" in content

    def test_desktop_file_location(self, tmp_root: Path):
        exec_path = tmp_root / "app.AppImage"
        exec_path.touch()

        result = create_desktop_entry(
            app_name="Test",
            exec_path=exec_path,
            root_override=tmp_root,
        )

        assert result.parent == applications_dir(tmp_root)

    def test_remove_desktop_entry(self, tmp_root: Path):
        exec_path = tmp_root / "app.AppImage"
        exec_path.touch()

        create_desktop_entry(
            app_name="ToRemove",
            exec_path=exec_path,
            root_override=tmp_root,
        )

        assert remove_desktop_entry("ToRemove", root_override=tmp_root)

    def test_remove_nonexistent(self, tmp_root: Path):
        assert not remove_desktop_entry("nope", root_override=tmp_root)


class TestIcon:
    def test_install_icon(self, tmp_root: Path):
        source = tmp_root / "icon.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n")

        result = install_icon(source, "TestApp", root_override=tmp_root)
        assert result.exists()
        assert result.parent == icons_dir(tmp_root) / "appdrop"

    def test_remove_icon(self, tmp_root: Path):
        source = tmp_root / "icon.png"
        source.write_bytes(b"\x89PNG\r\n\x1a\n")

        install_icon(source, "TestApp", root_override=tmp_root)
        assert remove_icon("TestApp", root_override=tmp_root)

    def test_remove_nonexistent_icon(self, tmp_root: Path):
        assert not remove_icon("nope", root_override=tmp_root)
