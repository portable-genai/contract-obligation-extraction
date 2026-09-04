"""Renewal clocks and the deadline register (pure date maths, explicit ``as_of``, no clock).

The kernel (:mod:`obligation_register.deadlines`) owns the primitives: whether a due date is
overdue, due-soon or upcoming relative to a supplied ``as_of``. This module layers the CONTRACTUAL
clock the catalog row calls for on top of them: a renewal or termination right is not actioned on
its due date, it is actioned a NOTICE PERIOD before it, so an obligation with a 90-day notice
period on a renewal 120 days out is already inside its action window today even though the renewal
itself is not "due soon". Everything here is a pure function of the deadline, the notice period
and the reference date, so a deadline register replays identically and a breached deadline is a
fact the engine computes, never one the model asserts.

A breached (overdue) deadline is consequential: the caller sets ``requires_human_review`` and routes
it to human-review-console, because a missed renewal notice can auto-renew a contract a firm meant
to exit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from obligation_register import DeadlineStatus, days_until, deadline_status

__all__ = [
    "DEFAULT_RENEWAL_POLICY",
    "DeadlineView",
    "RenewalPolicy",
    "action_by",
    "deadline_view",
]


@dataclass(frozen=True, slots=True)
class RenewalPolicy:
    """Config-owned windows for the deadline clock (practices check B4: the client's numbers).

    ``soon_within_days`` is the width of the kernel's DUE_SOON window; ``default_notice_days`` is
    the notice period assumed when an obligation carries a renewal/termination deadline but the
    extractor found no explicit notice period. Both are policy, so they live here and a
    deployment overrides them in a ``policy:`` block rather than editing the engine.
    """

    soon_within_days: int = 60
    default_notice_days: int = 30


#: The shipped default clock. A 60-day due-soon window and a 30-day fallback notice period are a
#: conservative starting point a client tunes to its own contract-management SLAs.
DEFAULT_RENEWAL_POLICY = RenewalPolicy()


def action_by(due_on: date, notice_days: int) -> date:
    """The date by which action must be taken: the due date less the notice period.

    A non-positive ``notice_days`` means no notice period, so the action date is the due date
    itself. Never returns a date after ``due_on``.
    """
    if notice_days <= 0:
        return due_on
    return due_on - timedelta(days=notice_days)


@dataclass(frozen=True, slots=True)
class DeadlineView:
    """One obligation's deadline resolved against an ``as_of`` date and its notice period.

    ``status`` is the kernel's verdict on the DUE date; ``in_notice_window`` is the contractual
    overlay: True when today is at or past the action-by date but the due date has not yet
    passed, i.e. the firm is inside the window in which it must act to renew or exit. ``breached``
    is a plain overdue: the due date is in the past relative to ``as_of``.
    """

    obligation_id: str
    due_on: date
    kind: str
    status: DeadlineStatus
    days_until: int
    notice_days: int
    action_by: date
    in_notice_window: bool
    breached: bool

    @property
    def actionable(self) -> bool:
        """True when this deadline needs attention now: overdue, due-soon, or inside its notice."""
        return self.breached or self.in_notice_window or self.status is DeadlineStatus.DUE_SOON


def deadline_view(
    obligation_id: str,
    due_on: date,
    kind: str,
    notice_days: int,
    as_of: date,
    policy: RenewalPolicy = DEFAULT_RENEWAL_POLICY,
) -> DeadlineView:
    """Resolve one deadline into a :class:`DeadlineView` (pure; the whole clock lives here)."""
    effective_notice = notice_days if notice_days > 0 else policy.default_notice_days
    act_by = action_by(due_on, effective_notice)
    status = deadline_status(due_on, as_of, policy.soon_within_days)
    delta = days_until(due_on, as_of)
    breached = delta < 0
    in_notice_window = (not breached) and as_of >= act_by
    return DeadlineView(
        obligation_id=obligation_id,
        due_on=due_on,
        kind=kind,
        status=status,
        days_until=delta,
        notice_days=effective_notice,
        action_by=act_by,
        in_notice_window=in_notice_window,
        breached=breached,
    )
