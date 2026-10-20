"""Application identity resolution.

Matches a dropped file to an existing managed installation using
available evidence (name, format).  Identity is treated as uncertain
when evidence is insufficient.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from appdrop.detect import PackageFormat, PackageInfo
from appdrop.registry import AppRecord, Registry

log = logging.getLogger(__name__)


class Confidence(Enum):
    """How confident we are that two packages are the same application."""

    HIGH = "high"        # Name and format match exactly
    MEDIUM = "medium"    # Name matches after normalisation
    LOW = "low"          # Only partial/heuristic match
    NONE = "none"        # No match found


@dataclass
class IdentityMatch:
    """Result of identity resolution."""

    existing: AppRecord | None = None
    confidence: Confidence = Confidence.NONE
    reason: str = ""

    @property
    def is_update(self) -> bool:
        """True if this looks like an update to an existing installation."""
        return self.existing is not None and self.confidence in (
            Confidence.HIGH, Confidence.MEDIUM
        )


class IdentityResolver:
    """Resolve whether a dropped file matches a managed installation."""

    def __init__(
        self,
        registry: Registry,
        *,
        deb_backend: object | None = None,
    ) -> None:
        self._registry = registry
        self._deb_backend = deb_backend

    def resolve(self, info: PackageInfo) -> IdentityMatch:
        """Find the best match for *info* among installed applications.

        Returns an :class:`IdentityMatch` with the matched record and
        confidence level.  Returns ``Confidence.NONE`` when no match is
        found.
        """
        if not info.name:
            return IdentityMatch(confidence=Confidence.NONE, reason="No name available")

        fmt = _format_key(info.format)

        # 1. Exact name + format match in registry
        exact = self._registry.find_app(info.name, fmt)
        if exact:
            return IdentityMatch(
                existing=exact,
                confidence=Confidence.HIGH,
                reason=f"Exact name match: {info.name}",
            )

        # 2. For Debian packages, also check host system if not in registry
        if fmt == "deb" and self._deb_backend is not None and hasattr(self._deb_backend, "query_system_package"):
            sys_pkg = self._deb_backend.query_system_package(info.name)
            if sys_pkg and sys_pkg.is_installed:
                return IdentityMatch(
                    existing=AppRecord(
                        name=sys_pkg.name,
                        display_name=sys_pkg.name,
                        format="deb",
                        version=sys_pkg.version,
                        architecture=sys_pkg.architecture,
                        status="installed",
                    ),
                    confidence=Confidence.HIGH,
                    reason=f"System package {sys_pkg.name} ({sys_pkg.version}) is installed",
                )

        # 3. Normalised name match
        normalised = _normalise(info.name)
        for app in self._registry.list_apps():
            if app.format != fmt:
                continue
            if _normalise(app.name) == normalised:
                return IdentityMatch(
                    existing=app,
                    confidence=Confidence.MEDIUM,
                    reason=f"Normalised name match: {_normalise(info.name)} ≈ {_normalise(app.name)}",
                )

        # 4. Display name match (looser)
        for app in self._registry.list_apps():
            if app.format != fmt:
                continue
            if app.display_name and _normalise(app.display_name) == normalised:
                return IdentityMatch(
                    existing=app,
                    confidence=Confidence.LOW,
                    reason=f"Display name match: {info.name} ≈ {app.display_name}",
                )

        return IdentityMatch(confidence=Confidence.NONE, reason="No matching installation found")


def _format_key(fmt: PackageFormat) -> str:
    """Convert PackageFormat to the registry format string."""
    if fmt == PackageFormat.APPIMAGE:
        return "appimage"
    if fmt == PackageFormat.DEB:
        return "deb"
    return "unknown"


def _normalise(name: str) -> str:
    """Normalise an application name for fuzzy matching.

    Lowercases and strips hyphens, underscores, and spaces.
    """
    return name.lower().replace("-", "").replace("_", "").replace(" ", "")
