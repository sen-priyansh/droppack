"""Debian package backend using APT and dpkg.

Performs safe metadata inspection, downgrade detection, and privileged
APT operations via pkexec.  Never executes dropped packages during
inspection or uses a shell interpreter.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from appdrop.detect import PackageInfo
from appdrop.registry import AppRecord, Registry, VersionRecord

log = logging.getLogger(__name__)

# Valid Debian package name pattern: starts with alphanumeric, can contain +, -, .
_DEB_PKG_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")


@dataclass
class DebInstalledInfo:
    """Information about a package currently installed on the host system."""

    name: str
    version: str
    status: str
    architecture: str

    @property
    def is_installed(self) -> bool:
        return "install ok installed" in self.status


@dataclass
class DebInstallResult:
    """Result of a Debian package operation."""

    success: bool
    package_name: str | None = None
    installed_version: str | None = None
    error: str | None = None
    is_downgrade: bool = False


# Type for custom command runner: (args: list[str]) -> subprocess.CompletedProcess
CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


class DebBackend:
    """Backend for managing Debian packages via APT and dpkg."""

    def __init__(
        self,
        registry: Registry,
        *,
        runner: CommandRunner | None = None,
        query_runner: CommandRunner | None = None,
    ) -> None:
        self._registry = registry
        self._runner = runner or self._default_runner
        self._query_runner = query_runner or self._default_runner

    @staticmethod
    def _default_runner(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )

    # ------------------------------------------------------------------
    # Query system state
    # ------------------------------------------------------------------

    def query_system_package(self, package_name: str) -> DebInstalledInfo | None:
        """Query dpkg for whether *package_name* is installed on the system."""
        if not package_name or not _DEB_PKG_NAME_RE.match(package_name):
            return None

        cmd = [
            "dpkg-query",
            "-W",
            "-f=${Status}\t${Version}\t${Architecture}\n",
            package_name,
        ]
        try:
            res = self._query_runner(cmd)
        except OSError as exc:
            log.warning("dpkg-query failed to execute: %s", exc)
            return None

        if res.returncode != 0 or not res.stdout.strip():
            return None

        parts = res.stdout.strip().split("\t")
        if len(parts) >= 3:
            return DebInstalledInfo(
                name=package_name,
                status=parts[0],
                version=parts[1],
                architecture=parts[2],
            )
        return None

    def compare_versions(self, ver1: str, op: str, ver2: str) -> bool:
        """Compare two Debian version strings using ``dpkg --compare-versions``."""
        cmd = ["dpkg", "--compare-versions", ver1, op, ver2]
        try:
            res = self._query_runner(cmd)
            return res.returncode == 0
        except OSError:
            # Fallback if dpkg binary not callable directly
            return False

    def check_downgrade(
        self, package_name: str, candidate_version: str | None
    ) -> tuple[bool, str | None]:
        """Check if *candidate_version* is a downgrade compared to installed version.

        Returns (is_downgrade, installed_version).
        """
        if not candidate_version:
            return False, None

        current = self.query_system_package(package_name)
        if not current or not current.is_installed or not current.version:
            return False, None

        # Compare: candidate < current ?
        if self.compare_versions(candidate_version, "lt", current.version):
            return True, current.version

        return False, current.version

    # ------------------------------------------------------------------
    # Install / Upgrade
    # ------------------------------------------------------------------

    def install(
        self,
        info: PackageInfo,
        *,
        allow_downgrade: bool = False,
    ) -> DebInstallResult:
        """Install or upgrade a Debian package using APT with privilege escalation."""
        if not info.filepath.is_file():
            return DebInstallResult(
                success=False,
                error=f"File does not exist: {info.filepath}",
            )

        pkg_name = info.name
        if not pkg_name or not _DEB_PKG_NAME_RE.match(pkg_name):
            return DebInstallResult(
                success=False,
                error=f"Invalid Debian package name: '{pkg_name}'",
            )

        # Check for downgrade
        is_dw, current_ver = self.check_downgrade(pkg_name, info.version)
        if is_dw and not allow_downgrade:
            return DebInstallResult(
                success=False,
                package_name=pkg_name,
                installed_version=current_ver,
                is_downgrade=True,
                error=(
                    f"Refusing to silently downgrade {pkg_name} from "
                    f"{current_ver} to {info.version}"
                ),
            )

        resolved_path = str(info.filepath.resolve())

        # Construct safe command list
        # We use apt-get install -y -- <path> with pkexec
        cmd = ["pkexec", "apt-get", "install", "-y", "--", resolved_path]
        log.info("Installing deb package via APT: %s", cmd)

        try:
            res = self._runner(cmd)
        except OSError as exc:
            return DebInstallResult(
                success=False,
                package_name=pkg_name,
                error=f"Execution error: {exc}",
            )

        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip() or f"Process exited with code {res.returncode}"
            return DebInstallResult(
                success=False,
                package_name=pkg_name,
                error=f"APT installation failed: {err_msg}",
            )

        # Post-installation verification: Verify the package is actually installed
        verified = self.query_system_package(pkg_name)
        if not verified or not verified.is_installed:
            return DebInstallResult(
                success=False,
                package_name=pkg_name,
                error="APT reported success, but package verification failed (not marked as installed)",
            )

        # Record in persistent registry
        now_ver = verified.version or info.version
        existing_rec = self._registry.find_app(pkg_name, "deb")

        if existing_rec:
            existing_rec.version = now_ver
            existing_rec.status = "installed"
            self._registry.update_app(existing_rec)
            app_id = existing_rec.id
            action = "update"
        else:
            new_rec = AppRecord(
                name=pkg_name,
                display_name=info.display_name,
                format="deb",
                version=now_ver,
                architecture=info.architecture or verified.architecture,
                description=info.description,
                install_path=resolved_path,
                status="installed",
            )
            app_id = self._registry.add_app(new_rec)
            action = "install"

        if app_id:
            self._registry.add_version(
                VersionRecord(
                    app_id=app_id,
                    version=now_ver,
                    action=action,
                    notes=f"APT {action} from {info.filepath.name}",
                )
            )

        log.info("Debian package %s (%s) installed successfully", pkg_name, now_ver)
        return DebInstallResult(
            success=True,
            package_name=pkg_name,
            installed_version=now_ver,
        )

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self, app_id: int) -> DebInstallResult:
        """Uninstall a system Debian package managed by AppDrop."""
        app = self._registry.get_app(app_id)
        if app is None:
            return DebInstallResult(success=False, error="Application not found in registry")

        pkg_name = app.name
        if not pkg_name or not _DEB_PKG_NAME_RE.match(pkg_name):
            return DebInstallResult(success=False, error=f"Invalid package name: '{pkg_name}'")

        cmd = ["pkexec", "apt-get", "remove", "-y", "--", pkg_name]
        log.info("Removing deb package via APT: %s", cmd)

        try:
            res = self._runner(cmd)
        except OSError as exc:
            return DebInstallResult(
                success=False,
                package_name=pkg_name,
                error=f"Execution error: {exc}",
            )

        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip() or f"Process exited with code {res.returncode}"
            return DebInstallResult(
                success=False,
                package_name=pkg_name,
                error=f"APT removal failed: {err_msg}",
            )

        # Check that it's no longer installed
        verified = self.query_system_package(pkg_name)
        if verified and verified.is_installed:
            return DebInstallResult(
                success=False,
                package_name=pkg_name,
                error="APT reported success, but package is still installed",
            )

        self._registry.remove_app(app_id)
        self._registry.add_version(
            VersionRecord(
                app_id=app_id,
                version=app.version,
                action="uninstall",
                notes="Uninstalled via APT",
            )
        )

        return DebInstallResult(success=True, package_name=pkg_name)
