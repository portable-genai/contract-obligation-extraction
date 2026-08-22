"""Both request paths open ONE span each, and neither span carries content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit store.
So the value of tracing these paths depends entirely on the spans carrying structural
attributes only: which action, whose, which tenant, which contract family. A case subject, a
counterparty, a clause's text, a register row or any narration reaching a span has left the
boundary the redaction exists to hold, and it has left it silently.

Two spans are pinned because this repo has two genuine request paths: the triage service
(``/v1/triage``) and the contract-register flow (``/v1/register``). The triage content case
drives the case whose text carries a planted NRIC; the register content case reads a real seed
contract, so the needles are values that would actually leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from contract_obligation_extraction.config import build_container
from contract_obligation_extraction.domain.corpus import AS_OF, contract_by_id
from contract_obligation_extraction.domain.models import TriageInput
from contract_obligation_extraction.domain.triage_service import TriageService
from contract_obligation_extraction.flow import RegisterOutcome, run_contract_register

from tests.conftest import local_settings
from tests.fixtures import sample_cases

#: Every attribute key each span is allowed to carry. A verdict that started explaining itself
#: on the span (a finding, a subject, a counterparty) would widen these sets, which is the
#: point of asserting on the set rather than on the individual keys.
_TRIAGE_KEYS = {"action", "actor"}
_REGISTER_KEYS = {"action", "actor", "tenant", "family"}

_MSA = "meridian-msa-2026"


class _RecordingTracer:
    """Captures every span name and attribute so the test can inspect what was emitted."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _triage(case: TriageInput) -> _RecordingTracer:
    container = build_container(local_settings())
    tracer = _RecordingTracer()
    TriageService(container.audit, tracer).triage(case, actor=sample_cases.ACTOR)  # type: ignore[arg-type]
    return tracer


def _register() -> tuple[_RecordingTracer, RegisterOutcome]:
    """The REAL local container, with only the tracer swapped for the recorder."""
    container = build_container(local_settings())
    tracer = _RecordingTracer()
    container.__dict__["tracer"] = tracer  # override the cached_property binding
    contract = contract_by_id(_MSA)
    assert contract is not None
    outcome = run_contract_register(
        container,
        contract,
        as_of=AS_OF,
        actor=sample_cases.ACTOR,
        tenant=sample_cases.TENANT,
    )
    return tracer, outcome


def _emitted(tracer: _RecordingTracer) -> str:
    """Every attribute VALUE that was emitted, and every KEY, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# The triage path
# --------------------------------------------------------------------------- #
def test_triaging_a_case_opens_exactly_one_named_span() -> None:
    tracer = _triage(sample_cases.ROUTINE_CASE)
    assert [name for name, _ in tracer.spans] == ["obligations.triage"]


def test_the_triage_span_carries_the_structural_attributes_an_operator_needs() -> None:
    _, attributes = _triage(sample_cases.ROUTINE_CASE).spans[0]
    assert attributes["action"] == "triage"
    assert attributes["actor"] == sample_cases.ACTOR


@pytest.mark.parametrize(
    "case",
    [sample_cases.ROUTINE_CASE, sample_cases.ESCALATING_CASE, sample_cases.PII_CASE],
    ids=["routine", "escalating", "pii"],
)
def test_the_triage_attribute_set_is_a_fixed_allowlist_whatever_the_band(
    case: TriageInput,
) -> None:
    """An escalation must not start attaching its reasons, or the case, to the span."""
    tracer = _triage(case)
    for _, attributes in tracer.spans:
        assert set(attributes) == _TRIAGE_KEYS


def test_no_triage_span_attribute_carries_case_content_or_the_planted_identifier() -> None:
    """The case used here has an NRIC planted in its text, so a leak would show."""
    tracer = _triage(sample_cases.PII_CASE)
    emitted = _emitted(tracer)
    for literal in (
        sample_cases.PLANTED_NRIC,
        sample_cases.PII_CASE.subject,
        sample_cases.PII_CASE.text,
        "ops@gamma.example",
    ):
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal not in emitted, f"a span attribute carried {literal!r}"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"


# --------------------------------------------------------------------------- #
# The contract-register path
# --------------------------------------------------------------------------- #
def test_reading_a_contract_opens_exactly_one_named_span() -> None:
    tracer, _ = _register()
    assert [name for name, _ in tracer.spans] == ["obligations.register"]


def test_the_register_span_carries_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose read is slow, on which tenant and family", and nothing more."""
    tracer, _ = _register()
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "register"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["tenant"] == sample_cases.TENANT
    assert attributes["family"] == "msa"
    assert set(attributes) == _REGISTER_KEYS


def test_no_register_span_attribute_carries_contract_content_or_register_rows() -> None:
    """Every content-shaped value in reach of the read: the contract and what it produced."""
    tracer, outcome = _register()
    emitted = _emitted(tracer)
    contract = contract_by_id(_MSA)
    assert contract is not None

    forbidden: list[str] = [
        contract.contract_id,
        contract.counterparty,
        outcome.register.subject,
        outcome.register.summary,
        outcome.note.text,
    ]
    forbidden.extend(clause.text for clause in contract.clauses())
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal not in emitted, f"a span attribute carried {literal!r}"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    triage_tracer = _triage(sample_cases.ESCALATING_CASE)
    register_tracer, _ = _register()
    values: list[Any] = [
        value
        for tracer in (triage_tracer, register_tracer)
        for _, attributes in tracer.spans
        for value in attributes.values()
    ]
    assert values
    assert all(isinstance(value, str) for value in values)
