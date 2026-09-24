"""The runtime-control seam: what switched-off routing binds, and what a caller reports.

**Disabled adapter.** When a deployment switches review routing off
(``CONTRACT_REVIEW_ROUTING=off``), the container binds :class:`DisabledReviewRouter` instead of
the profile's class. It satisfies the port and submits nothing, and the container logs the
posture at startup.

**Recording wrapper.** Every caller that hands a result to the router (the triage route, the
agent tools, the CLI, and the contract-register flow they share) wraps the bound router in
:class:`RecordingReviewRouter` for that one call, so what it returns can say what happened:
``routed``, ``failed``, ``off`` or ``not_required``. A failure is logged and absorbed here rather
than failing an already-built, already-audited register or triage, but it is never invisible:
the caller reports ``failed`` and an empty reference, which nobody can mistake for a reviewed
result.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from ..config import Settings
from ..domain.models import TriageResult

_log = logging.getLogger(__name__)


class ReviewRouting(StrEnum):
    """What happened to the human-review hand-off for one result."""

    ROUTED = "routed"
    FAILED = "failed"
    OFF = "off"
    NOT_REQUIRED = "not_required"


class DisabledReviewRouter:
    """ReviewRouterPort with routing switched off: nothing is submitted anywhere."""

    enabled = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def route(self, result: TriageResult, *, maker: str, tenant: str = "") -> str:
        return ""


class RecordingReviewRouter:
    """Wraps the bound review router for one caller and records each hand-off's outcome."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self._outcomes: list[ReviewRouting] = []

    def route(self, result: TriageResult, *, maker: str, tenant: str = "") -> str:
        """Hand ``result`` off if it requires review; return the reference, empty if none."""
        if not result.requires_human_review:
            return ""
        if not getattr(self._inner, "enabled", True):
            self._outcomes.append(ReviewRouting.OFF)
            return ""
        try:
            reference = self._inner.route(result, maker=maker, tenant=tenant)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - the outcome is reported, never raised
            _log.warning("human-review hand-off failed: %s", type(exc).__name__)
            self._outcomes.append(ReviewRouting.FAILED)
            return ""
        self._outcomes.append(ReviewRouting.ROUTED)
        return str(reference)

    @property
    def outcome(self) -> ReviewRouting:
        """One value for the caller: any failure wins, then off, then routed."""
        for worst in (ReviewRouting.FAILED, ReviewRouting.OFF, ReviewRouting.ROUTED):
            if worst in self._outcomes:
                return worst
        return ReviewRouting.NOT_REQUIRED
