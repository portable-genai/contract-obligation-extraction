"""On-prem AuditSinkPort: fail-fast portability placeholder (the sovereign-exit proof, P-12)."""

from __future__ import annotations

from ...config import Settings
from ...domain.kernel import AuditEvent


class OnPremAuditAdapter:
    """Satisfies AuditSinkPort but refuses at call time: the client wires its own WORM store."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def record(self, event: AuditEvent) -> None:
        raise NotImplementedError(
            "on-prem audit sink is a portability placeholder: bind the client's own "
            "append-only WORM store (see docs/onprem-migration.md)"
        )
