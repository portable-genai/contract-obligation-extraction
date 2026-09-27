"""The deterministic triage service: pure decision, redact-before-audit, soft escalation.

The consequential decision (the severity band and whether to escalate) is pure stdlib and
replayable; an LLM would only narrate, never produce the band. PII is redacted BEFORE anything
is written to the audit sink (P-04), every result carries a citation, and a consequential
result escalates softly to a human (P-06) rather than auto-executing.

Rule R1: the guardrail screens BOTH directions of the one generation call this service makes,
the narrated ``summary`` (a fork that replaces the deterministic body of :meth:`_narrate` with a
real model call inherits this screening unchanged, because it wraps the STEP, not the string).
INPUT, before anything is scored or narrated: every caller-supplied field on its own, the case
subject as well as its text, because each reaches the summary, the citation and the audit record
by itself; and then the PROMPT the generation step receives, the screened fields joined. The
joined screen is not redundant: an injection split across the two fields ("... ignore all" in
the subject, "previous instructions ..." in the text) passes each field's screen, and only a
screen of the text the model actually reads sees it whole. OUTPUT: the narrated summary is
screened before it is audited or returned. The text each screen hands back is the text used from
then on, exactly as given.

A blocked direction is audited ``Decision.BLOCKED`` and raises
:class:`~.errors.GuardrailBlockedError`, never a partial result. A guardrail that cannot decide
(its backend errored or timed out) fails CLOSED the same way: the refusal is audited BLOCKED
when the audit sink can take it, and the guardrail's own error then reaches the caller.
"""

from __future__ import annotations

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.guardrail import GuardrailPort
from ..ports.observability import ObservabilityTracerPort
from .errors import GuardrailBlockedError
from .kernel import AuditEvent, Citation, Decision, Direction, GuardrailVerdict, Severity, utcnow
from .models import TriageInput, TriageResult
from .pii import PII_PATTERNS

# Deterministic keyword bands (the vertical IP; swap for your policy). Ordered most severe first.
_SEVERITY_KEYWORDS: tuple[tuple[Severity, frozenset[str]], ...] = (
    (Severity.CRITICAL, frozenset({"sanction", "terrorism", "fraud"})),
    (Severity.HIGH, frozenset({"breach", "leak", "urgent", "weapon"})),
    (Severity.MEDIUM, frozenset({"complaint", "dispute", "delay"})),
)


def narration_prompt(subject: str, text: str) -> str:
    """The prompt the generation step receives: both screened fields, joined as sent.

    The subject line, a blank line, then the text, with nothing between them that a screen
    could read as a break in a phrase that runs across the two.
    """
    return f"{subject}\n\n{text}"


#: One span per triaged case. Structural attributes only: see :meth:`TriageService.triage`.
_TRIAGE_SPAN = "obligations.triage"


class TriageService:
    """Score a case into a severity band and record an already-redacted audit event."""

    def __init__(
        self,
        audit: AuditSinkPort,
        tracer: ObservabilityTracerPort,
        guardrail: GuardrailPort,
    ) -> None:
        self._audit = audit
        self._tracer = tracer
        self._guardrail = guardrail

    def triage(self, case: TriageInput, *, actor: str) -> TriageResult:
        """Band one case deterministically and write the redacted audit record.

        The whole path runs inside one span. Its attributes are STRUCTURAL only, never the
        case subject or its text: a trace backend is not the WORM audit trail. It has no
        redaction stage, a wider read audience and no retention rule written against a
        regulator's requirement, so anything content-shaped that reaches a span has left the
        boundary the ``redact`` call exists to hold, and left it silently.
        """
        with self._tracer.span(_TRIAGE_SPAN, action="triage", actor=actor):
            return self._triage(case, actor=actor)

    def _triage(self, case: TriageInput, *, actor: str) -> TriageResult:
        # 1) Guardrail screen (INPUT), before the case is scored or narrated at all (rule R1).
        # Nothing has been scored yet, so a refusal here records NO severity rather than a band
        # nothing produced, and no subject, because the subject may be the very thing refused.
        subject = self._screen(case.subject, Direction.INPUT, actor=actor)
        text = self._screen(case.text, Direction.INPUT, actor=actor)
        # The prompt a generation call receives is screened AS SENT, after its parts: a fork's
        # model reads this string, so this string is what has to have passed the INPUT screen.
        prompt = self._screen(
            narration_prompt(subject, text), Direction.INPUT, actor=actor, subject=subject
        )

        severity = self._severity(text)
        escalate = severity in (Severity.HIGH, Severity.CRITICAL)
        decision = Decision.ESCALATED if escalate else Decision.ALLOWED
        narrated = self._narrate(prompt, subject, severity)

        # 2) Guardrail screen (OUTPUT) on the narrated summary, before it is audited or returned.
        # This is the step a real generation call replaces `narrated` above at: the screen stays
        # in exactly this place regardless of what produces the text.
        summary = self._screen(
            narrated, Direction.OUTPUT, actor=actor, subject=subject, severity=severity
        )

        citation = Citation(
            source_id=f"case:{subject}",
            title="Case description",
            snippet=text[:80],
        )

        # Redact BEFORE the audit write: the raw identifiers never reach the WORM record.
        self._audit.record(
            AuditEvent(
                action="triage",
                actor=actor,
                decision=decision,
                severity=severity,
                redacted_summary=redact(f"{summary} :: {text}", PII_PATTERNS),
                citations=(citation,),
                timestamp=utcnow(),
            )
        )

        return TriageResult(
            subject=subject,
            severity=severity,
            decision=decision,
            summary=summary,
            requires_human_review=escalate,
            citations=(citation,),
        )

    def _screen(
        self,
        text: str,
        direction: Direction,
        *,
        actor: str,
        subject: str | None = None,
        severity: Severity | None = None,
    ) -> str:
        """Screen one text in one direction; return the text to use from here on, or refuse.

        The returned text is the verdict's ``sanitized_text`` exactly as given, including an
        empty string: a screen that redacted everything has not asked for the original back.
        A block, and a guardrail that raised instead of deciding, both fail closed after an
        audited BLOCKED record. ``subject`` and ``severity`` are what the record may state,
        and each is ``None`` where it was not (yet) screened or scored.
        """
        try:
            verdict: GuardrailVerdict = self._guardrail.screen(text, direction)
        except Exception as exc:
            reason = f"guardrail unavailable ({type(exc).__name__})"
            try:
                self._audit_blocked(actor, direction, reason, subject=subject, severity=severity)
            except Exception as audit_exc:
                exc.add_note(f"the BLOCKED audit record could not be written: {audit_exc!r}")
            raise
        if not verdict.allowed or verdict.sanitized_text is None:
            reason = verdict.reason or f"triage {direction.value} blocked by guardrail"
            self._audit_blocked(actor, direction, reason, subject=subject, severity=severity)
            raise GuardrailBlockedError(reason)
        return verdict.sanitized_text

    def _audit_blocked(
        self,
        actor: str,
        direction: Direction,
        reason: str,
        *,
        subject: str | None,
        severity: Severity | None,
    ) -> None:
        """Audit a guardrail refusal BEFORE the raise reaches the caller (rule R1/P-04).

        Never carries the refused text: only that a refusal happened, in which direction, and
        why, plus the subject once it has itself passed the INPUT screen. A refused attempt is a
        security-relevant event the WORM trail must hold even though the request as a whole
        never produced a triage.
        """
        what = f"{subject}: blocked" if subject is not None else "blocked"
        self._audit.record(
            AuditEvent(
                action="triage",
                actor=actor,
                decision=Decision.BLOCKED,
                severity=severity,
                redacted_summary=redact(f"{what} ({direction.value}): {reason}", PII_PATTERNS),
                citations=(),
                timestamp=utcnow(),
            )
        )

    @staticmethod
    def _narrate(prompt: str, subject: str, severity: Severity) -> str:
        """The generation step: the one place a fork puts its model call, on ``prompt``.

        ``prompt`` is the screened, joined prompt, so a fork that sends it to a model sends
        text the INPUT screen has seen whole. The deterministic stand-in narrates from the
        subject and the band, and does not read the prompt.
        """
        return f"{subject}: triaged {severity.value}"

    @staticmethod
    def _severity(text: str) -> Severity:
        lowered = text.lower()
        for severity, keywords in _SEVERITY_KEYWORDS:
            if any(word in lowered for word in keywords):
                return severity
        return Severity.LOW
