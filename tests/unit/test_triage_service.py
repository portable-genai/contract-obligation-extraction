"""The deterministic triage service: severity bands, soft escalation, redact-before-audit."""

from __future__ import annotations

from contract_obligation_extraction.adapters.local.audit import (
    LocalAuditAdapter,
)
from contract_obligation_extraction.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from contract_obligation_extraction.config import (
    Settings,
)
from contract_obligation_extraction.domain.kernel import (
    Decision,
    Severity,
)
from contract_obligation_extraction.domain.models import (
    TriageInput,
)
from contract_obligation_extraction.domain.triage_service import (
    TriageService,
)


def _service() -> tuple[TriageService, LocalAuditAdapter]:
    settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(settings)
    return TriageService(audit, LocalNoopTracerAdapter(settings)), audit


def _severity(text: str) -> Severity:
    service, _ = _service()
    return service.triage(TriageInput("X", text), actor="a").severity


def test_severity_bands_are_deterministic() -> None:
    assert _severity("possible fraud") is Severity.CRITICAL
    assert _severity("data breach") is Severity.HIGH
    assert _severity("billing dispute") is Severity.MEDIUM
    assert _severity("all fine") is Severity.LOW


def test_high_and_critical_escalate_softly() -> None:
    service, _ = _service()
    high = service.triage(TriageInput("X", "urgent leak"), actor="a")
    assert high.decision is Decision.ESCALATED
    assert high.requires_human_review is True

    low = service.triage(TriageInput("X", "routine note"), actor="a")
    assert low.decision is Decision.ALLOWED
    assert low.requires_human_review is False


def test_pii_is_redacted_before_the_audit_write() -> None:
    service, audit = _service()
    service.triage(
        TriageInput("Gamma LLP", "urgent breach, NRIC S1234567D on file"),
        actor="analyst@bank.example",
    )
    records = audit.log.read_all()
    assert records, "an audit event should have been recorded"
    summary = records[-1]["redacted_summary"]
    # The raw identifier never reaches the WORM record; the actor is the verified principal.
    assert "S1234567D" not in summary
    assert "REDACTED" in summary
    assert records[-1]["actor"] == "analyst@bank.example"
    assert audit.log.verify_chain().ok
