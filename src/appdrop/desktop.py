"""Desktop integration — .desktop file and icon management.

Creates, updates, and removes ``.desktop`` entries and icons in the user's
XDG applications directory for AppImage-managed applications.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

from appdrop.config import APP_NAME

log = logging.getLogger(__name__)

# Standard XDG path for user-level .desktop files
_APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"
_ICONS_DIR = Path.home() / ".local" / "share" / "icons"


def applications_dir(root_override: Path | None = None) -> Path:
    """Directory for .desktop files."""
    if root_override is not None:
        return root_override / ".local" / "share" / "applications"
    return _APPLICATIONS_DIR


def icons_dir(root_override: Path | None = None) -> Path:
    """Directory for application icons."""
    if root_override is not None:
        return root_override / ".local" / "share" / "icons"
    return _ICONS_DIR


def create_desktop_entry(
    *,
    app_name: str,
    exec_path: Path,
    icon_path: Path | None = None,
    comment: str | None = None,
    categories: str = "Utility;",
    root_override: Path | None = None,
) -> Path:
    """Create a ``.desktop`` file for an AppImage.

    Returns the path to the created file.
    """
    desktop_id = f"{APP_NAME}-{_sanitise(app_name)}.desktop"
    dest_dir = applications_dir(root_override)
    dest_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = dest_dir / desktop_id

    icon_value = str(icon_path) if icon_path and icon_path.exists() else app_name

    content = textwrap.dedent(f"""\
        [Desktop Entry]
        Type=Application
        Name={app_name}
        Exec={exec_path}
        Icon={icon_value}
        Comment={comment or f'{app_name} (managed by AppDrop)'}
        Categories={categories}
        Terminal=false
        X-AppDrop-Managed=true
    """)

    desktop_path.write_text(content, encoding="utf-8")
    desktop_path.chmod(0o644)

    log.info("Created desktop entry: %s", desktop_path)

    # Update desktop database (best-effort)
    _update_desktop_database(dest_dir)

    return desktop_path


def remove_desktop_entry(
    app_name: str,
    *,
    root_override: Path | None = None,
) -> bool:
    """Remove the .desktop file for *app_name*.

    Returns True if a file was actually removed.
    """
    desktop_id = f"{APP_NAME}-{_sanitise(app_name)}.desktop"
    desktop_path = applications_dir(root_override) / desktop_id

    if desktop_path.exists():
        desktop_path.unlink()
        log.info("Removed desktop entry: %s", desktop_path)
        _update_desktop_database(applications_dir(root_override))
        return True

    log.debug("Desktop entry not found: %s", desktop_path)
    return False


def install_icon(
    source: Path,
    app_name: str,
    *,
    root_override: Path | None = None,
) -> Path:
    """Copy an icon file into the user's icon directory.

    Returns the destination path.
    """
    dest_dir = icons_dir(root_override) / APP_NAME
    dest_dir.mkdir(parents=True, exist_ok=True)

    suffix = source.suffix or ".png"
    dest = dest_dir / f"{_sanitise(app_name)}{suffix}"

    shutil.copy2(source, dest)
    log.info("Installed icon: %s → %s", source, dest)
    return dest


def remove_icon(
    app_name: str,
    *,
    root_override: Path | None = None,
) -> bool:
    """Remove the icon for *app_name*. Returns True if found and removed."""
    icon_dir = icons_dir(root_override) / APP_NAME
    if not icon_dir.exists():
        return False

    removed = False
    for f in icon_dir.iterdir():
        if f.stem == _sanitise(app_name):
            f.unlink()
            removed = True
            log.info("Removed icon: %s", f)
    return removed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitise(name: str) -> str:
    """Sanitise a name for use in filenames (lowercase, hyphens only)."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower()).strip("-")


def _update_desktop_database(directory: Path) -> None:
    """Run ``update-desktop-database`` on *directory* (best-effort)."""
    exe = shutil.which("update-desktop-database")
    if not exe:
        return
    try:
        subprocess.run(
            [exe, str(directory)],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("update-desktop-database failed: %s", exc)
