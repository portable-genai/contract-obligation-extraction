"""The admission engine: uncited candidates dropped, dedup, needs-review, severity, replay.

These lock the consequential guarantees the plan names for contract-obligation-extraction: every
admitted obligation links to a real clause (a fabricated anchor is dropped, never defaulted), a
duplicate collapses on the shared kernel key, an ambiguous or unresolved classification is held for
review, the severity band is pure code, the cross-tenant read is a 403 not a 404, and the
third-party-risk-ddq feed carries a schema version.
"""

from __future__ import annotations

from datetime import date

import pytest
from obligation_register import SCHEMA_VERSION

from contract_obligation_extraction.adapters.local.audit import LocalAuditAdapter
from contract_obligation_extraction.config import Settings
from contract_obligation_extraction.domain.contracts import (
    CrossTenantError,
    RegisterService,
    admit_contract,
    authorize_contract_access,
    register_envelope,
)
from contract_obligation_extraction.domain.corpus import AS_OF, contract_by_id, proposals_for
from contract_obligation_extraction.domain.flags import RiskFlag
from contract_obligation_extraction.domain.kernel import Decision, Severity

_MSA = "meridian-msa-2026"
_SOW = "meridian-sow-014"
_OUT = "apex-outsourcing-2026"
_ISDA = "global-isda-2026"


def _service() -> RegisterService:
    return RegisterService(LocalAuditAdapter(Settings(profile="local", audit_path=":memory:")))


def _register(contract_id: str):
    contract = contract_by_id(contract_id)
    assert contract is not None
    return _service().build(
        contract, proposals_for(contract_id), as_of=AS_OF, actor="analyst@bank.example"
    )


def test_a_candidate_citing_an_unreal_clause_is_dropped_not_defaulted() -> None:
    reg = _register(_MSA)
    # The MSA proposals include a candidate anchored to clause 9, which does not exist.
    assert len(reg.dropped) == 1
    assert all(row.clause_number != "9" for row in reg.obligations)
    assert all(row.clause_anchor.startswith(_MSA) for row in reg.obligations)


def test_a_duplicate_candidate_dedups_on_the_shared_key() -> None:
    reg = _register(_MSA)
    # Two identical liability candidates were proposed; exactly one obligation admits.
    liability = [r for r in reg.obligations if RiskFlag.LIABILITY_CAP in r.flags]
    assert len(liability) == 1


def test_an_always_review_flag_and_an_ambiguous_row_are_held_for_review() -> None:
    msa = _register(_MSA)
    step_in = next(r for r in msa.obligations if RiskFlag.AUDIT_STEP_IN in r.flags)
    assert step_in.needs_review is True

    isda = _register(_ISDA)
    ambiguous = next(r for r in isda.obligations if not r.flags)
    assert ambiguous.needs_review is True, "the model-flagged-ambiguous row must hold for review"


def test_an_unknown_proposed_flag_is_dropped_and_the_row_held_for_review() -> None:
    dpa = _register("meridian-dpa-2026")
    row = next(r for r in dpa.obligations if r.clause_number == "5")
    assert row.flags == (), "a flag outside the taxonomy is dropped, never coerced"
    assert row.needs_review is True, "an unresolved classification is held, not silently emptied"


def test_a_breached_renewal_notice_lifts_severity_and_escalates() -> None:
    reg = _register(_OUT)
    breached = next(r for r in reg.obligations if r.deadline and r.deadline.breached)
    assert breached.needs_review is True
    assert reg.severity is Severity.HIGH
    assert reg.decision is Decision.ESCALATED
    assert reg.requires_human_review is True


def test_a_clean_statement_of_work_does_not_escalate() -> None:
    reg = _register(_SOW)
    assert reg.severity is Severity.LOW
    assert reg.requires_human_review is False
    assert all(not r.flags for r in reg.obligations)


def test_every_admitted_obligation_carries_a_clause_citation() -> None:
    reg = _register(_MSA)
    for row in reg.obligations:
        assert row.citation.source_id == _MSA
        assert row.citation.locator == row.clause_number


def test_the_register_replays_byte_identically() -> None:
    first = register_envelope(_register(_MSA))
    second = register_envelope(_register(_MSA))
    assert first == second


def test_the_rgc8_feed_carries_a_schema_version() -> None:
    envelope = register_envelope(_register(_MSA))
    assert envelope["schema_version"] == SCHEMA_VERSION
    assert envelope["kind"] == "contract_obligation_register"
    assert "payload" in envelope


def test_cross_tenant_access_raises_and_the_home_tenant_does_not() -> None:
    contract = contract_by_id(_MSA)
    assert contract is not None
    authorize_contract_access("demo-bank", contract_tenant=contract.tenant)  # no raise
    with pytest.raises(CrossTenantError):
        authorize_contract_access("other-bank", contract_tenant=contract.tenant)


def test_admission_is_pure_and_independent_of_the_service_wiring() -> None:
    contract = contract_by_id(_MSA)
    assert contract is not None
    a = admit_contract(contract, proposals_for(_MSA), as_of=date(2026, 6, 1))
    b = admit_contract(contract, proposals_for(_MSA), as_of=date(2026, 6, 1))
    assert [r.obligation_id for r in a.rows] == [r.obligation_id for r in b.rows]
    assert a.dropped == b.dropped
