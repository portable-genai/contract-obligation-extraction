"""On-prem ReviewRouterPort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

The client runs its own review and approval workflow, so this binding refuses at call time
rather than dropping the escalation. Refusing is the correct failure: a router that silently
returned would convert every consequential result into an unreviewed one.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import TriageResult


class OnPremReviewRouter:
    """Satisfies ReviewRouterPort but refuses: the client wires its own maker-checker queue."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def route(self, result: TriageResult, *, maker: str, tenant: str = "") -> str:
        raise NotImplementedError(
            "on-prem review routing is a portability placeholder: bind the client's own "
            "maker-checker queue (see docs/onprem-migration.md). Rule R8 still applies: an "
            "escalated result must reach a human reviewer."
        )
