"""Local ReviewRouterPort: enqueue the routed review to an in-memory outbox (no live Hrz7).

Exercises the R8 routing path offline. An escalated result is converted to a review and enqueued
into the same transactional outbox the managed adapter flushes to Hrz7, so the offline gate, the
tests and the demo can assert that an escalation was ROUTED, not merely flagged, without a
running console. The outbox is deliberately not a no-op: a silent local router would let a
producer ship with R8 unwired and a green gate.
"""

from __future__ import annotations

from review_kit import InMemoryOutbox

from ...config import Settings
from ...domain.models import TriageResult
from .._review_payload import result_to_review

#: The actor recorded against every queued review. A module constant, not an inline literal:
#: the repository slug is a rendered value whose length nobody here controls, and a name that
#: only ever sits on its own line cannot push a statement past the line-length limit.
_ROUTING_ACTOR = "contract-obligation-extraction"


class LocalReviewRouter:
    """Record routed reviews in an in-memory outbox for the SDK-free ``local`` profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._outbox = InMemoryOutbox()

    def route(self, result: TriageResult, *, maker: str, tenant: str = "") -> str:
        review = result_to_review(result, maker=maker, tenant=tenant or self._settings.tenant)
        self._outbox.enqueue(review, actor=_ROUTING_ACTOR)
        # The queue reference, not a console id: nothing has been submitted yet, and saying so
        # is the point. `flush(client)` drains this outbox once a console is reachable.
        return f"outbox:{len(self._outbox.pending())}:{review.source_key}"

    @property
    def outbox(self) -> InMemoryOutbox:
        """Expose the outbox for inspection in tests, the eval and the demo."""
        return self._outbox
