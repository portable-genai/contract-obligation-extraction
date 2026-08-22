"""AuditSinkPort: the WORM audit boundary (the hexagon edge for observability, rule R2)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.kernel import AuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Append one immutable, already-redacted audit record."""
        ...
