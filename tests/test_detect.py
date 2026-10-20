"""Tests for appdrop.detect — format detection and metadata extraction."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from appdrop.detect import (
    PackageFormat,
    PackageInfo,
    _parse_appimage_filename,
    _parse_deb_control,
    detect,
    detect_format,
)


# ---------------------------------------------------------------------------
# Helpers: create minimal test files
# ---------------------------------------------------------------------------


def _make_deb(path: Path, *, corrupt: bool = False) -> Path:
    """Create a minimal file with Debian ar-archive magic."""
    path.write_bytes(b"!<arch>\n" + (b"\x00" * 100 if not corrupt else b""))
    return path


def _make_appimage_type2(path: Path) -> Path:
    """Create a minimal file with ELF + AppImage Type 2 magic."""
    header = b"\x7fELF" + b"\x00" * 4 + b"AI\x02" + b"\x00" * 100
    path.write_bytes(header)
    return path


def _make_appimage_by_ext(path: Path) -> Path:
    """Create an ELF file that is only recognised by extension."""
    header = b"\x7fELF" + b"\x00" * 200
    path.write_bytes(header)
    return path


def _make_random_file(path: Path) -> Path:
    """Create a file with unrecognised content."""
    path.write_bytes(b"NOTATHING" + b"\x00" * 100)
    return path


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


class TestDetectFormat:
    def test_deb_magic(self, tmp_path: Path):
        f = _make_deb(tmp_path / "test.deb")
        assert detect_format(f) == PackageFormat.DEB

    def test_appimage_type2_magic(self, tmp_path: Path):
        f = _make_appimage_type2(tmp_path / "Test.AppImage")
        assert detect_format(f) == PackageFormat.APPIMAGE

    def test_appimage_by_extension(self, tmp_path: Path):
        f = _make_appimage_by_ext(tmp_path / "Test.AppImage")
        assert detect_format(f) == PackageFormat.APPIMAGE

    def test_elf_without_appimage_ext(self, tmp_path: Path):
        """An ELF without AI magic and without .AppImage extension → UNKNOWN."""
        f = _make_appimage_by_ext(tmp_path / "test_binary")
        assert detect_format(f) == PackageFormat.UNKNOWN

    def test_unknown_format(self, tmp_path: Path):
        f = _make_random_file(tmp_path / "garbage.bin")
        assert detect_format(f) == PackageFormat.UNKNOWN

    def test_nonexistent_file(self, tmp_path: Path):
        assert detect_format(tmp_path / "nope.deb") == PackageFormat.UNKNOWN

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty"
        f.write_bytes(b"")
        assert detect_format(f) == PackageFormat.UNKNOWN

    def test_tiny_file(self, tmp_path: Path):
        f = tmp_path / "tiny"
        f.write_bytes(b"\x7f")
        assert detect_format(f) == PackageFormat.UNKNOWN


# ---------------------------------------------------------------------------
# Full detection pipeline
# ---------------------------------------------------------------------------


class TestDetect:
    def test_nonexistent_file(self, tmp_path: Path):
        info = detect(tmp_path / "missing.deb")
        assert info.error is not None
        assert info.format == PackageFormat.UNKNOWN

    def test_deb_returns_packageinfo(self, tmp_path: Path):
        f = _make_deb(tmp_path / "pkg.deb")
        info = detect(f)
        assert info.format == PackageFormat.DEB
        assert info.filepath == f
        assert info.size_bytes > 0

    def test_appimage_returns_packageinfo(self, tmp_path: Path):
        f = _make_appimage_type2(tmp_path / "App-1.0-x86_64.AppImage")
        info = detect(f)
        assert info.format == PackageFormat.APPIMAGE
        assert info.filepath == f
        # Metadata should fall back to filename parsing
        assert info.name == "App"
        assert info.version == "1.0"

    def test_unknown_format_has_error(self, tmp_path: Path):
        f = _make_random_file(tmp_path / "unknown.xyz")
        info = detect(f)
        assert info.format == PackageFormat.UNKNOWN
        assert info.error is not None

    def test_display_name_with_name(self, tmp_path: Path):
        info = PackageInfo(filepath=tmp_path / "test.deb", name="my-package")
        assert info.display_name == "my-package"

    def test_display_name_without_name(self, tmp_path: Path):
        info = PackageInfo(filepath=tmp_path / "test.deb")
        assert info.display_name == "test"


# ---------------------------------------------------------------------------
# Deb control parsing
# ---------------------------------------------------------------------------


class TestParseDebControl:
    def test_parses_standard_fields(self):
        text = (
            " Package: hello\n"
            " Version: 2.10-3\n"
            " Architecture: amd64\n"
            " Description: example package\n"
            " Maintainer: Test <test@test.com>\n"
        )
        info = PackageInfo(filepath=Path("/fake.deb"))
        _parse_deb_control(info, text)
        assert info.name == "hello"
        assert info.version == "2.10-3"
        assert info.architecture == "amd64"
        assert info.description == "example package"

    def test_handles_empty_text(self):
        info = PackageInfo(filepath=Path("/fake.deb"))
        _parse_deb_control(info, "")
        assert info.name is None
        assert info.version is None


# ---------------------------------------------------------------------------
# AppImage filename parsing
# ---------------------------------------------------------------------------


class TestParseAppImageFilename:
    @pytest.mark.parametrize(
        "filename, expected_name, expected_version, expected_arch",
        [
            ("MyApp-1.2.3-x86_64.AppImage", "MyApp", "1.2.3", "x86_64"),
            ("my-app-0.1.0-aarch64.AppImage", "my-app", "0.1.0", "aarch64"),
            ("App_2.0_amd64.AppImage", "App", "2.0", "amd64"),
            ("Simple-3.0.AppImage", "Simple", "3.0", None),
            ("tool-1.0.0-beta.1-x86_64.AppImage", "tool", "1.0.0-beta.1", "x86_64"),
        ],
    )
    def test_known_patterns(
        self, filename: str, expected_name: str,
        expected_version: str, expected_arch: str | None,
    ):
        info = PackageInfo(filepath=Path(f"/tmp/{filename}"))
        _parse_appimage_filename(info)
        assert info.name == expected_name
        assert info.version == expected_version
        assert info.architecture == expected_arch

    def test_unparseable_filename(self):
        info = PackageInfo(filepath=Path("/tmp/SomeWeirdName.AppImage"))
        _parse_appimage_filename(info)
        # Should fall back to using stem
        assert info.name == "SomeWeirdName"

    def test_does_not_overwrite_existing(self):
        info = PackageInfo(
            filepath=Path("/tmp/App-1.0.AppImage"),
            name="Already Set",
            version="9.9",
        )
        _parse_appimage_filename(info)
        assert info.name == "Already Set"
        assert info.version == "9.9"
