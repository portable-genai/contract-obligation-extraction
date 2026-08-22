"""Vertical artifact models: this service's own request and result types.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for
no reason but the length of its name.

A fork building a different vertical rewrites this module and keeps ``kernel.py`` untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from .kernel import Citation, Decision, Severity


@dataclass(frozen=True, slots=True)
class TriageInput:
    """One case to triage: a subject and its free-text description."""

    subject: str
    text: str


@dataclass(frozen=True, slots=True)
class TriageResult:
    """The triage decision: a severity, a soft-escalation flag, and cited reasoning."""

    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    citations: tuple[Citation, ...] = ()
