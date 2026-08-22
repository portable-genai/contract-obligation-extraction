"""The renewal clock: breached, inside-notice-window and upcoming, against a hand-computed oracle.

The clock is the consequential deadline engine: a missed renewal notice can auto-renew a contract
a firm meant to exit, so whether today is breached or inside a notice window must be pure date
maths a reviewer can replay, never a model's assertion.
"""

from __future__ import annotations

from datetime import date

from contract_obligation_extraction.domain.renewals import (
    DEFAULT_RENEWAL_POLICY,
    RenewalPolicy,
    action_by,
    deadline_view,
)


def test_action_by_subtracts_the_notice_period() -> None:
    assert action_by(date(2026, 8, 1), 90) == date(2026, 5, 3)
    assert action_by(date(2026, 8, 1), 0) == date(2026, 8, 1)  # no notice: act by the due date


def test_a_past_due_date_is_breached() -> None:
    dv = deadline_view("o1", date(2026, 5, 15), "renewal_notice", 60, date(2026, 6, 1))
    assert dv.breached is True
    assert dv.actionable is True


def test_inside_the_notice_window_before_the_due_date() -> None:
    # Due 2026-08-01, 90-day notice -> act by 2026-05-03; as_of 2026-06-01 is past that but the
    # due date has not passed, so it is inside the notice window and not breached.
    dv = deadline_view("o1", date(2026, 8, 1), "renewal_notice", 90, date(2026, 6, 1))
    assert dv.breached is False
    assert dv.in_notice_window is True
    assert dv.action_by == date(2026, 5, 3)


def test_a_far_deadline_is_upcoming_and_not_actionable() -> None:
    dv = deadline_view("o1", date(2026, 12, 15), "deliverable", 0, date(2026, 6, 1))
    assert dv.breached is False
    assert dv.in_notice_window is False
    assert dv.actionable is False


def test_the_notice_period_falls_back_to_policy_when_absent() -> None:
    policy = RenewalPolicy(soon_within_days=60, default_notice_days=30)
    dv = deadline_view("o1", date(2026, 7, 1), "renewal", 0, date(2026, 6, 15), policy)
    assert dv.notice_days == 30
    assert dv.action_by == date(2026, 6, 1)


def test_status_replays_identically() -> None:
    args = ("o1", date(2026, 7, 1), "renewal", 30, date(2026, 6, 1), DEFAULT_RENEWAL_POLICY)
    assert deadline_view(*args) == deadline_view(*args)
