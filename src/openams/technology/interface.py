"""Backend protocol for technology implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import (
    TechnologyCapabilities,
    TechnologyIdentity,
    TechnologyLookupRequest,
    TechnologyLookupResult,
)


@runtime_checkable
class TechnologyBackend(Protocol):
    """Technology-independent lookup backend contract."""

    @property
    def identity(self) -> TechnologyIdentity:
        ...

    @property
    def capabilities(self) -> TechnologyCapabilities:
        ...

    def lookup(
        self,
        request: TechnologyLookupRequest,
    ) -> TechnologyLookupResult:
        ...
