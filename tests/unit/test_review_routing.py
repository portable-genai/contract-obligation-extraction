"""Rule R8: an escalated result is ROUTED to human-review-console, not left in a per-repo boolean.

This is the standing gate for the failure the rule exists to prevent. A repo can set
``requires_human_review = True``, pass every other test, and still auto-execute in practice
because nothing ever reads the flag. So the assertions here are about the ROUTING, not the flag:
an escalation produces an outbound review, a non-escalation produces none, the payload leaves
redacted, and the on-prem placeholder refuses rather than swallowing the escalation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from contract_obligation_extraction.adapters.gcp.review_router import (
    CloudReviewRouter,
)
from contract_obligation_extraction.adapters.local.review_router import (
    LocalReviewRouter,
)
from contract_obligation_extraction.adapters.onprem.review_router import (
    OnPremReviewRouter,
)
from contract_obligation_extraction.api.app import (
    app,
)
from contract_obligation_extraction.config import (
    Settings,
    build_container,
)
from contract_obligation_extraction.domain.kernel import (
    Severity,
)
from contract_obligation_extraction.domain.models import (
    TriageInput,
    TriageResult,
)
from contract_obligation_extraction.domain.triage_service import (
    TriageService,
)


def _settings(profile: str = "local") -> Settings:
    return Settings(profile=profile, audit_path=":memory:", tenant="demo-bank")


def _service() -> TriageService:
    container = build_container(_settings())
    return TriageService(container.audit, container.tracer)


def _result(text: str, subject: str = "Acme Holdings (FICTIONAL)") -> TriageResult:
    return _service().triage(TriageInput(subject, text), actor="analyst@bank.example")


def test_an_escalated_result_produces_an_outbound_review() -> None:
    router = LocalReviewRouter(_settings())
    ref = router.route(_result("urgent data breach"), maker="analyst@bank.example")
    assert ref, "routing must return a reference, so the caller can record where it went"
    pending = router.outbox.pending()
    assert len(pending) == 1
    review = pending[0].review
    assert review.maker == "analyst@bank.example"
    assert review.tenant == "demo-bank"
    assert review.severity == Severity.HIGH.value
    assert review.source_key, "a durable outbox needs an idempotency key"


def test_a_critical_result_demands_dual_control() -> None:
    router = LocalReviewRouter(_settings())
    router.route(_result("suspected fraud"), maker="analyst@bank.example")
    assert router.outbox.pending()[0].review.required_approvals == 2


def test_the_payload_is_redacted_before_it_leaves_the_process() -> None:
    """human-review-console is a shared sink; a raw identifier must never reach the wire."""
    router = LocalReviewRouter(_settings())
    result = _result("urgent breach, NRIC S1234567D on file", subject="Gamma LLP")
    router.route(result, maker="analyst@bank.example")
    review = router.outbox.pending()[0].review
    wire = repr(review.to_payload())
    assert "S1234567D" not in wire
    assert "REDACTED" in wire


def test_the_managed_router_refuses_when_no_console_is_configured() -> None:
    """An escalation with nowhere to go must fail loudly, not return as if it were reviewed."""
    router = CloudReviewRouter(Settings(profile="gcp", audit_path=":memory:", review_url=""))
    with pytest.raises(RuntimeError, match="R8"):
        router.route(_result("urgent data breach"), maker="analyst@bank.example")


def test_the_onprem_placeholder_refuses_rather_than_dropping_the_escalation() -> None:
    router = OnPremReviewRouter(_settings("onprem"))
    with pytest.raises(NotImplementedError, match="R8"):
        router.route(_result("urgent data breach"), maker="analyst@bank.example")


def test_the_api_routes_the_escalation_in_the_same_request() -> None:
    """The serving path, not just the adapter: an escalation must not depend on a later job."""
    client = TestClient(app, client=("127.0.0.1", 50000))
    escalated = client.post(
        "/v1/triage",
        json={"subject": "Acme Holdings (FICTIONAL)", "text": "urgent data breach"},
        headers={"X-Dev-Persona": "auditor"},
    ).json()
    assert escalated["requires_human_review"] is True
    assert escalated["review_ref"], "an escalation with no routing reference went nowhere"

    routine = client.post(
        "/v1/triage",
        json={"subject": "Acme Holdings (FICTIONAL)", "text": "routine note"},
        headers={"X-Dev-Persona": "auditor"},
    ).json()
    assert routine["requires_human_review"] is False
    assert routine["review_ref"] == "", "a non-escalation must not manufacture a review"
