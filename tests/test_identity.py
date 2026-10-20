"""Tests for appdrop.identity — identity resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from appdrop.detect import PackageFormat, PackageInfo
from appdrop.identity import Confidence, IdentityMatch, IdentityResolver, _normalise
from appdrop.registry import AppRecord, Registry


@pytest.fixture()
def registry(tmp_root: Path) -> Registry:
    reg = Registry(root_override=tmp_root)
    reg.open()
    yield reg
    reg.close()


@pytest.fixture()
def resolver(registry: Registry) -> IdentityResolver:
    return IdentityResolver(registry)


def _info(name: str = "TestApp", version: str = "2.0", fmt: PackageFormat = PackageFormat.APPIMAGE) -> PackageInfo:
    return PackageInfo(filepath=Path(f"/tmp/{name}.AppImage"), format=fmt, name=name, version=version)


class TestNormalise:
    def test_lowercase(self):
        assert _normalise("MyApp") == "myapp"

    def test_strips_separators(self):
        assert _normalise("my-app_test") == "myapptest"

    def test_strips_spaces(self):
        assert _normalise("My App") == "myapp"


class TestIdentityResolver:
    def test_exact_match(self, resolver: IdentityResolver, registry: Registry):
        registry.add_app(AppRecord(name="TestApp", format="appimage", version="1.0"))
        match = resolver.resolve(_info(name="TestApp"))
        assert match.is_update
        assert match.confidence == Confidence.HIGH
        assert match.existing is not None
        assert match.existing.name == "TestApp"

    def test_normalised_match(self, resolver: IdentityResolver, registry: Registry):
        registry.add_app(AppRecord(name="test-app", format="appimage", version="1.0"))
        match = resolver.resolve(_info(name="TestApp"))
        assert match.is_update
        assert match.confidence == Confidence.MEDIUM

    def test_display_name_match(self, resolver: IdentityResolver, registry: Registry):
        registry.add_app(AppRecord(name="internal-name", display_name="TestApp", format="appimage", version="1.0"))
        match = resolver.resolve(_info(name="TestApp"))
        assert match.confidence == Confidence.LOW

    def test_no_match(self, resolver: IdentityResolver, registry: Registry):
        registry.add_app(AppRecord(name="OtherApp", format="appimage", version="1.0"))
        match = resolver.resolve(_info(name="TestApp"))
        assert not match.is_update
        assert match.confidence == Confidence.NONE

    def test_different_format_no_match(self, resolver: IdentityResolver, registry: Registry):
        registry.add_app(AppRecord(name="TestApp", format="deb", version="1.0"))
        match = resolver.resolve(_info(name="TestApp", fmt=PackageFormat.APPIMAGE))
        assert not match.is_update

    def test_no_name(self, resolver: IdentityResolver):
        info = PackageInfo(filepath=Path("/tmp/test"), format=PackageFormat.APPIMAGE)
        match = resolver.resolve(info)
        assert match.confidence == Confidence.NONE

    def test_empty_registry(self, resolver: IdentityResolver):
        match = resolver.resolve(_info())
        assert match.confidence == Confidence.NONE

    def test_identity_match_is_update(self):
        match = IdentityMatch(existing=AppRecord(name="x", format="appimage"), confidence=Confidence.HIGH)
        assert match.is_update

    def test_identity_match_not_update_on_low(self):
        match = IdentityMatch(existing=AppRecord(name="x", format="appimage"), confidence=Confidence.LOW)
        assert not match.is_update
