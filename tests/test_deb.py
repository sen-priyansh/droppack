"""Tests for appdrop.backends.deb — Debian package backend."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from appdrop.backends.deb import DebBackend, DebInstalledInfo, DebInstallResult
from appdrop.detect import PackageFormat, PackageInfo
from appdrop.registry import AppRecord, Registry


@pytest.fixture()
def registry(tmp_root: Path) -> Registry:
    reg = Registry(root_override=tmp_root)
    reg.open()
    yield reg
    reg.close()


def _make_real_deb(
    path: Path,
    name: str = "testpkg",
    version: str = "1.0",
    arch: str = "all",
) -> Path:
    """Create a valid Debian package using dpkg-deb."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "pkg"
        (root / "DEBIAN").mkdir(parents=True)
        (root / "DEBIAN" / "control").write_text(
            f"Package: {name}\n"
            f"Version: {version}\n"
            f"Architecture: {arch}\n"
            f"Maintainer: Test <test@example.com>\n"
            f"Description: A test package\n"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["dpkg-deb", "-b", str(root), str(path)],
            check=True,
            capture_output=True,
        )
    return path


def _make_info(filepath: Path, name: str = "testpkg", version: str = "1.0") -> PackageInfo:
    return PackageInfo(
        filepath=filepath,
        format=PackageFormat.DEB,
        name=name,
        version=version,
        architecture="all",
        description="A test package",
    )


class TestDebBackendQuery:
    def test_query_installed_system_package(self, registry: Registry):
        # Query a standard package that exists on the system (like bash or dpkg)
        backend = DebBackend(registry)
        info = backend.query_system_package("dpkg")
        assert info is not None
        assert info.name == "dpkg"
        assert info.is_installed
        assert info.version != ""

    def test_query_nonexistent_package(self, registry: Registry):
        backend = DebBackend(registry)
        info = backend.query_system_package("nonexistent_pkg_xyz_999")
        assert info is None

    def test_query_invalid_package_name(self, registry: Registry):
        backend = DebBackend(registry)
        assert backend.query_system_package("Invalid Name; rm -rf /") is None
        assert backend.query_system_package("") is None

    def test_compare_versions(self, registry: Registry):
        backend = DebBackend(registry)
        assert backend.compare_versions("1.0", "lt", "2.0")
        assert backend.compare_versions("2.0", "gt", "1.0")
        assert backend.compare_versions("1.0-1", "eq", "1.0-1")
        assert not backend.compare_versions("1.0", "gt", "2.0")


class TestDebBackendInstall:
    def test_mock_install_success(self, registry: Registry, tmp_path: Path):
        deb_file = _make_real_deb(tmp_path / "myapp_1.0_all.deb", name="myapp", version="1.0")
        info = _make_info(deb_file, name="myapp", version="1.0")

        # Mock runner simulates successful apt-get
        executed_cmds = []

        def mock_runner(cmd: list[str]) -> subprocess.CompletedProcess:
            executed_cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Success", stderr="")

        # Mock query runner simulates package being installed after install
        def mock_query(cmd: list[str]) -> subprocess.CompletedProcess:
            if "dpkg-query" in cmd[0]:
                pkg = cmd[-1]
                if pkg == "myapp" and executed_cmds:
                    return subprocess.CompletedProcess(
                        cmd,
                        returncode=0,
                        stdout="install ok installed\t1.0\tall\n",
                        stderr="",
                    )
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

        backend = DebBackend(registry, runner=mock_runner, query_runner=mock_query)
        result = backend.install(info)

        assert result.success
        assert result.package_name == "myapp"
        assert result.installed_version == "1.0"

        # Verify command arguments list: no shell=True, safe structure
        assert len(executed_cmds) == 1
        cmd = executed_cmds[0]
        assert cmd[0] == "pkexec"
        assert cmd[1] == "apt-get"
        assert cmd[2] == "install"
        assert "-y" in cmd
        assert "--" in cmd
        assert str(deb_file.resolve()) in cmd

        # Verify in registry
        app = registry.find_app("myapp", "deb")
        assert app is not None
        assert app.version == "1.0"
        history = registry.get_versions(app.id)
        assert len(history) == 1
        assert history[0].action == "install"

    def test_prevent_silent_downgrade(self, registry: Registry, tmp_path: Path):
        deb_file = _make_real_deb(tmp_path / "myapp_1.0_all.deb", name="myapp", version="1.0")
        info = _make_info(deb_file, name="myapp", version="1.0")

        # Mock query runner reports currently installed version is 2.0
        def mock_query(cmd: list[str]) -> subprocess.CompletedProcess:
            if "dpkg-query" in cmd[0]:
                return subprocess.CompletedProcess(
                    cmd,
                    returncode=0,
                    stdout="install ok installed\t2.0\tall\n",
                    stderr="",
                )
            if "dpkg" in cmd[0] and "--compare-versions" in cmd:
                # 1.0 lt 2.0
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

        runner_called = False

        def mock_runner(cmd: list[str]) -> subprocess.CompletedProcess:
            nonlocal runner_called
            runner_called = True
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        backend = DebBackend(registry, runner=mock_runner, query_runner=mock_query)

        # Attempt install without allow_downgrade
        result = backend.install(info, allow_downgrade=False)
        assert not result.success
        assert result.is_downgrade
        assert "downgrade" in (result.error or "").lower()
        assert not runner_called

        # Now attempt with allow_downgrade=True
        result2 = backend.install(info, allow_downgrade=True)
        assert runner_called

    def test_verification_failure(self, registry: Registry, tmp_path: Path):
        deb_file = _make_real_deb(tmp_path / "myapp_1.0_all.deb", name="myapp", version="1.0")
        info = _make_info(deb_file, name="myapp", version="1.0")

        def mock_runner(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="Done", stderr="")

        # Query runner says package is NOT installed
        def mock_query(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="not found")

        backend = DebBackend(registry, runner=mock_runner, query_runner=mock_query)
        result = backend.install(info)

        assert not result.success
        assert "verification failed" in (result.error or "").lower()

    def test_apt_failure_reported(self, registry: Registry, tmp_path: Path):
        deb_file = _make_real_deb(tmp_path / "myapp_1.0_all.deb", name="myapp", version="1.0")
        info = _make_info(deb_file, name="myapp", version="1.0")

        def mock_runner(cmd: list[str]) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(
                cmd,
                returncode=100,
                stdout="",
                stderr="E: Unable to locate package",
            )

        backend = DebBackend(registry, runner=mock_runner)
        result = backend.install(info)

        assert not result.success
        assert "E: Unable to locate package" in (result.error or "")

    def test_uninstall_deb(self, registry: Registry):
        rec = AppRecord(
            name="myapp",
            display_name="MyApp",
            format="deb",
            version="1.0",
            status="installed",
        )
        app_id = registry.add_app(rec)

        executed_cmds = []

        def mock_runner(cmd: list[str]) -> subprocess.CompletedProcess:
            executed_cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        def mock_query(cmd: list[str]) -> subprocess.CompletedProcess:
            # Package is no longer installed
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="")

        backend = DebBackend(registry, runner=mock_runner, query_runner=mock_query)
        res = backend.uninstall(app_id)

        assert res.success
        assert len(executed_cmds) == 1
        assert executed_cmds[0] == ["pkexec", "apt-get", "remove", "-y", "--", "myapp"]

        # Check registry marked removed
        app = registry.get_app(app_id)
        assert app is not None
        assert app.status == "removed"
