#!/usr/bin/env python3
"""Build a standard Debian package (.deb) for DropPack."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src" / "droppack"
DATA_DIR = REPO_ROOT / "data"
BUILD_DIR = REPO_ROOT / "build" / "deb"
DIST_DIR = REPO_ROOT / "dist"

VERSION = "0.1.0"
PACKAGE_NAME = f"droppack_{VERSION}_all.deb"


def build_deb() -> Path:
    """Stage files and build the Debian package using dpkg-deb."""
    print("Building DropPack Debian package...")

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Staging directory layout
    debian_dir = BUILD_DIR / "DEBIAN"
    bin_dir = BUILD_DIR / "usr" / "bin"
    python_dir = BUILD_DIR / "usr" / "lib" / "python3" / "dist-packages" / "droppack"
    apps_dir = BUILD_DIR / "usr" / "share" / "applications"

    for d in (debian_dir, bin_dir, python_dir, apps_dir):
        d.mkdir(parents=True)

    # 2. Control file
    control_content = f"""Package: droppack
Version: {VERSION}
Section: utils
Priority: optional
Architecture: all
Maintainer: DropPack Maintainers <dev@droppack.local>
Depends: python3 (>= 3.10), python3-pyside6, dpkg, pkexec
Description: Drag-and-drop installer for AppImage and Debian packages
 DropPack is a simple Linux desktop utility that installs and manages
 AppImage and Debian packages through drag-and-drop.
 .
 Target distributions include Pop!_OS and Ubuntu/Debian-based desktops.
"""
    (debian_dir / "control").write_text(control_content, encoding="utf-8")

    # 3. Copy python source files (ignoring __pycache__)
    for item in SRC_DIR.rglob("*.py"):
        rel = item.relative_to(SRC_DIR)
        dest = python_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)

    # 4. Create launcher executable in /usr/bin/droppack
    launcher = bin_dir / "droppack"
    launcher_content = """#!/usr/bin/env python3
import sys
from droppack.__main__ import main
if __name__ == "__main__":
    sys.exit(main())
"""
    launcher.write_text(launcher_content, encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH | 0o755)

    # 5. Desktop entry
    desktop_src = DATA_DIR / "droppack.desktop"
    if desktop_src.exists():
        shutil.copy2(desktop_src, apps_dir / "droppack.desktop")

    # 6. Run dpkg-deb -b
    out_deb = DIST_DIR / PACKAGE_NAME
    cmd = ["dpkg-deb", "--build", str(BUILD_DIR), str(out_deb)]
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

    print(f"\nDebian package created successfully: {out_deb}")

    # Inspect package
    print("\nPackage Info:")
    subprocess.run(["dpkg-deb", "--info", str(out_deb)], check=True)
    print("\nPackage Contents:")
    subprocess.run(["dpkg-deb", "--contents", str(out_deb)], check=True)

    return out_deb


if __name__ == "__main__":
    out = build_deb()
    print(f"\nBuilt: {out}")
