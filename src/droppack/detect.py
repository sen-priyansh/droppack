"""Package format detection and metadata extraction.

Identifies whether a file is an AppImage or Debian package by inspecting
magic bytes, then extracts available metadata **without executing** the file.
"""

from __future__ import annotations

import enum
import hashlib
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class PackageFormat(enum.Enum):
    """Recognised package formats."""

    APPIMAGE = "AppImage"
    DEB = "Debian Package"
    UNKNOWN = "Unknown"


@dataclass
class PackageInfo:
    """Metadata extracted from a dropped file."""

    filepath: Path
    format: PackageFormat = PackageFormat.UNKNOWN
    name: str | None = None
    version: str | None = None
    description: str | None = None
    architecture: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    dependencies: list[str] = field(default_factory=list)
    icon_bytes: bytes | None = None
    icon_format: str | None = None
    raw_metadata: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    @property
    def display_name(self) -> str:
        """Human-readable name, falling back to filename."""
        return self.name or self.filepath.stem

    @property
    def format_label(self) -> str:
        return self.format.value


# ---------------------------------------------------------------------------
# Magic bytes
# ---------------------------------------------------------------------------

_ELF_MAGIC = b"\x7fELF"
_APPIMAGE_TYPE2_MAGIC = b"AI\x02"  # At offset 8 in Type-2 AppImages
_DEB_MAGIC = b"!<arch>\n"
_SQUASHFS_MAGIC = b"hsqs"


# ---------------------------------------------------------------------------
# Format detection (magic bytes only — never executes the file)
# ---------------------------------------------------------------------------


def detect_format(filepath: Path) -> PackageFormat:
    """Determine package format by inspecting magic bytes.

    Returns ``PackageFormat.UNKNOWN`` if the file cannot be read or does
    not match a known format.
    """
    try:
        with open(filepath, "rb") as f:
            header = f.read(16)
    except OSError as exc:
        log.warning("Cannot read %s: %s", filepath, exc)
        return PackageFormat.UNKNOWN

    if len(header) < 8:
        return PackageFormat.UNKNOWN

    # Debian packages are ar archives starting with "!<arch>\n"
    if header[:8] == _DEB_MAGIC:
        return PackageFormat.DEB

    # AppImage Type 2: ELF with "AI\x02" at offset 8
    if header[:4] == _ELF_MAGIC:
        if len(header) >= 11 and header[8:11] == _APPIMAGE_TYPE2_MAGIC:
            return PackageFormat.APPIMAGE
        # Fallback: trust the file extension for ELF files
        if filepath.suffix.lower() == ".appimage":
            return PackageFormat.APPIMAGE

    return PackageFormat.UNKNOWN


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------


def detect(filepath: Path) -> PackageInfo:
    """Detect format and extract metadata from *filepath*.

    This is the main entry point.  It never executes the file.
    """
    filepath = Path(filepath)
    info = PackageInfo(filepath=filepath)

    if not filepath.is_file():
        info.error = "File does not exist or is not a regular file"
        return info

    info.format = detect_format(filepath)
    info.size_bytes = filepath.stat().st_size

    # Compute SHA-256 checksum safely
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        info.sha256 = h.hexdigest()
    except OSError:
        pass

    if info.format == PackageFormat.DEB:
        _extract_deb_metadata(info)
    elif info.format == PackageFormat.APPIMAGE:
        _extract_appimage_metadata(info)
    else:
        info.error = "Unrecognised package format"

    return info


# ---------------------------------------------------------------------------
# .deb metadata  (dpkg-deb — safe, read-only)
# ---------------------------------------------------------------------------

# Fields we extract from the debian control file
_DEB_FIELDS = ("Package", "Version", "Architecture", "Description",
               "Maintainer", "Section", "Installed-Size")


def _extract_deb_metadata(info: PackageInfo) -> None:
    """Populate *info* from ``dpkg-deb --info``."""
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb:
        info.error = "dpkg-deb not found on this system"
        return

    try:
        result = subprocess.run(
            [dpkg_deb, "--info", str(info.filepath)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        info.error = "dpkg-deb timed out"
        return
    except OSError as exc:
        info.error = f"Failed to run dpkg-deb: {exc}"
        return

    if result.returncode != 0:
        info.error = f"dpkg-deb error: {result.stderr.strip()}"
        return

    _parse_deb_control(info, result.stdout)


def _parse_deb_control(info: PackageInfo, text: str) -> None:
    """Parse dpkg-deb --info output into *info* fields."""
    for line in text.splitlines():
        line = line.strip()
        match = re.match(r"^(\w[\w-]*):\s*(.*)", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        info.raw_metadata[key] = value

    info.name = info.raw_metadata.get("Package")
    info.version = info.raw_metadata.get("Version")
    info.architecture = info.raw_metadata.get("Architecture")
    info.description = info.raw_metadata.get("Description")
    deps_raw = info.raw_metadata.get("Depends", "")
    if deps_raw:
        info.dependencies = [d.strip() for d in deps_raw.split(",") if d.strip()]


# ---------------------------------------------------------------------------
# AppImage metadata  (never executes the binary)
# ---------------------------------------------------------------------------


def _extract_appimage_metadata(info: PackageInfo) -> None:
    """Extract metadata from an AppImage's embedded squashfs.

    Uses ``unsquashfs`` to read the ``.desktop`` file from the squashfs
    filesystem without executing the AppImage.  Falls back to parsing the
    filename if unsquashfs is not available.
    """
    # Try unsquashfs first
    unsquashfs = shutil.which("unsquashfs")
    if unsquashfs:
        try:
            _extract_appimage_desktop_entry(info, unsquashfs)
            return
        except Exception as exc:
            log.debug("unsquashfs extraction failed: %s", exc)

    # Fallback: parse name and version from filename
    _parse_appimage_filename(info)


def _extract_appimage_desktop_entry(info: PackageInfo, unsquashfs: str) -> None:
    """Extract .desktop file from embedded squashfs and parse it."""
    # First, find the squashfs offset
    offset = _find_squashfs_offset(info.filepath)
    if offset is None:
        _parse_appimage_filename(info)
        return

    # List files in the squashfs to find the .desktop file
    try:
        result = subprocess.run(
            [unsquashfs, "-o", str(offset), "-l", str(info.filepath)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        _parse_appimage_filename(info)
        return

    if result.returncode != 0:
        _parse_appimage_filename(info)
        return

    list_output = result.stdout

    # Find .desktop files in the listing
    desktop_files = []
    for line in list_output.splitlines():
        stripped = line.strip()
        if stripped.endswith(".desktop"):
            # Extract the path part (unsquashfs -l output format: "squashfs-root/file.desktop")
            desktop_files.append(stripped)

    if not desktop_files:
        _parse_appimage_filename(info)
        return

    # Pick the first .desktop file at the root level
    target = None
    for df in desktop_files:
        # Prefer files directly under squashfs-root/
        parts = df.replace("squashfs-root/", "").split("/")
        if len(parts) == 1:
            target = df
            break
    if target is None:
        target = desktop_files[0]

    # Extract the .desktop file content
    # The path from unsquashfs -l may include prefixes; extract just the relative path
    rel_path = target
    if "squashfs-root/" in rel_path:
        rel_path = rel_path.split("squashfs-root/", 1)[1]

    try:
        result = subprocess.run(
            [unsquashfs, "-o", str(offset), "-cat", str(info.filepath), rel_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        _parse_appimage_filename(info)
        return

    if result.returncode != 0:
        # Try without -cat (older versions)
        _parse_appimage_filename(info)
        return

    _parse_desktop_entry(info, result.stdout)

    # If we still have no name, fall back to filename
    if not info.name:
        _parse_appimage_filename(info)

    # Try extracting the icon (.DirIcon or root .png / .svg)
    icon_target = None
    for line in list_output.splitlines():
        stripped = line.strip()
        if stripped.endswith(".DirIcon"):
            icon_target = stripped
            break
        if stripped.endswith(".png") or stripped.endswith(".svg"):
            parts = stripped.replace("squashfs-root/", "").split("/")
            if len(parts) == 1:
                icon_target = stripped

    if icon_target:
        icon_rel = icon_target.split("squashfs-root/", 1)[-1] if "squashfs-root/" in icon_target else icon_target
        try:
            icon_res = subprocess.run(
                [unsquashfs, "-o", str(offset), "-cat", str(info.filepath), icon_rel],
                capture_output=True,
                timeout=15,
            )
            if icon_res.returncode == 0 and icon_res.stdout:
                info.icon_bytes = icon_res.stdout
                info.icon_format = "svg" if icon_target.endswith(".svg") else "png"
        except (subprocess.TimeoutExpired, OSError):
            pass


def _find_squashfs_offset(filepath: Path) -> int | None:
    """Find the byte offset of the embedded squashfs filesystem."""
    try:
        with open(filepath, "rb") as f:
            # Read in chunks to find squashfs magic
            chunk_size = 64 * 1024
            offset = 0
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                idx = chunk.find(_SQUASHFS_MAGIC)
                if idx >= 0:
                    return offset + idx
                # Overlap to avoid missing magic at chunk boundary
                offset += chunk_size - 4
                f.seek(offset)
    except OSError:
        pass
    return None


def _parse_desktop_entry(info: PackageInfo, text: str) -> None:
    """Parse a .desktop file's [Desktop Entry] section."""
    in_section = False
    for line in text.splitlines():
        line = line.strip()
        if line == "[Desktop Entry]":
            in_section = True
            continue
        if line.startswith("[") and in_section:
            break
        if not in_section or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        info.raw_metadata[key] = value

    info.name = info.raw_metadata.get("Name", info.name)
    info.version = info.raw_metadata.get("X-AppImage-Version",
                   info.raw_metadata.get("Version", info.version))
    info.description = info.raw_metadata.get("Comment", info.description)


# Common AppImage filename patterns:
#   AppName-1.2.3-x86_64.AppImage
#   AppName-1.2.3.AppImage
#   appname_1.2.3_amd64.AppImage
_KNOWN_ARCHES = frozenset({"x86_64", "aarch64", "armhf", "i386", "i686", "amd64"})


def _parse_appimage_filename(info: PackageInfo) -> None:
    """Best-effort metadata from the filename alone.

    Strategy: strip the ``.AppImage`` suffix, then split on ``-`` or ``_``.
    Walk the tokens from left to right; the first token starting with a
    digit is assumed to begin the version string.  If the last token is a
    known architecture it is separated out.
    """
    stem = info.filepath.stem  # e.g. "MyApp-1.2.3-x86_64"
    if not stem:
        return

    # Check for and strip a trailing architecture string *before* tokenising,
    # because some arch names contain underscores (e.g. "x86_64").
    arch: str | None = None
    remaining = stem
    for a in sorted(_KNOWN_ARCHES, key=len, reverse=True):
        for sep in ("-", "_"):
            suffix = sep + a
            if remaining.endswith(suffix):
                arch = a
                remaining = remaining[: -len(suffix)]
                break
        if arch:
            break

    # Split on - or _
    tokens = re.split(r"[-_]", remaining)

    # Find the first token that starts with a digit → version boundary
    name_parts: list[str] = []
    version_parts: list[str] = []
    found_version = False
    for tok in tokens:
        if not found_version and tok and tok[0].isdigit():
            found_version = True
        if found_version:
            version_parts.append(tok)
        else:
            name_parts.append(tok)

    name = "-".join(name_parts) if name_parts else None
    version = "-".join(version_parts) if version_parts else None

    # If the entire stem was digits (unlikely), treat as name
    if not name_parts and version_parts:
        name = stem
        version = None

    info.name = info.name or name or stem
    info.version = info.version or version
    info.architecture = info.architecture or arch
