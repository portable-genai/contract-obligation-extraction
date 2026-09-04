"""ReviewRouterPort: the boundary that routes an escalated result to human-review-console (rule R8).

Rule R8 is the reason this port exists. A producer that sets ``requires_human_review`` MUST hand
the item to the human-review-console; terminating the escalation in a
per-repo boolean is the failure this port removes, because a flag nobody reads is
auto-execution with extra steps. Setting the flag and calling :meth:`route` is one act, not two
optional ones: ``api.app`` and the CLI both call it on every escalated result.

The domain stays pure. This port names the hand-off; the adapters (not this module) depend on
the shared ``review-kit`` client and perform the S2S submission.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import TriageResult


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, result: TriageResult, *, maker: str, tenant: str = "") -> str:
        """Route an escalated result to human-review-console and return the routing reference.

        ``maker`` is the VERIFIED principal that originated the underlying decision, never a
        client-asserted actor. The return value is the console's review id where the console
        answered, or a local queue reference where the submission was buffered; it is never
        empty, so a caller can record what happened to the escalation.
        """
        ...
