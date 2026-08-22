"""The not-falsely-green proof: the extraction and flag metrics can go red, per family.

A metric that cannot fall when the thing it measures genuinely breaks proves nothing. This wires
``agent_eval_kit.assert_each_can_go_red`` over two families of metric:

* **flag classification, per flag family.** For each of the seven flag families, the real proposal
  carries the flag (scores 1.0) and a degraded proposal with the flag stripped scores 0.0. A
  family whose degraded case still passed would be a metric that cannot see a dropped flag.
* **clause linkage, per contract family.** For each contract, the real proposals admit their
  clauses (scores 1.0) and a corrupted set citing unreal anchors admits nothing (scores 0.0).

If any degraded case still met the bar, ``assert_each_can_go_red`` fails with that family named.
"""

from __future__ import annotations

from dataclasses import replace

from agent_eval_kit import assert_each_can_go_red

from contract_obligation_extraction.domain.contracts import Contract, admit_contract
from contract_obligation_extraction.domain.corpus import AS_OF, contract_by_id, proposals_for
from contract_obligation_extraction.domain.flags import RiskFlag
from contract_obligation_extraction.ports.extraction import ExtractionResult

# One (contract, clause, flag) witness per flag family, drawn from the seed corpus.
_FLAG_WITNESS: dict[str, tuple[str, str, RiskFlag]] = {
    "termination_renewal": ("meridian-msa-2026", "1", RiskFlag.TERMINATION_RENEWAL),
    "liability_cap": ("meridian-msa-2026", "3", RiskFlag.LIABILITY_CAP),
    "indemnity": ("meridian-msa-2026", "4", RiskFlag.INDEMNITY),
    "audit_step_in": ("meridian-msa-2026", "5", RiskFlag.AUDIT_STEP_IN),
    "sub_outsourcing": ("meridian-msa-2026", "6", RiskFlag.SUB_OUTSOURCING),
    "data_residency": ("meridian-dpa-2026", "1", RiskFlag.DATA_RESIDENCY),
    "sla_commitment": ("apex-outsourcing-2026", "4", RiskFlag.SLA_COMMITMENT),
}

_CONTRACTS = (
    "meridian-msa-2026",
    "meridian-sow-014",
    "meridian-dpa-2026",
    "apex-outsourcing-2026",
    "global-isda-2026",
)


def _get(contract_id: str) -> Contract:
    contract = contract_by_id(contract_id)
    assert contract is not None
    return contract


def _strip_flag(result: ExtractionResult, anchor: str) -> ExtractionResult:
    """Return the extraction result with the flags removed from one clause's proposal."""
    candidates = tuple(
        replace(c, proposed_flags=()) if c.clause_anchor == anchor else c for c in result.candidates
    )
    return replace(result, candidates=candidates)


def _corrupt_anchors(result: ExtractionResult) -> ExtractionResult:
    """Return the result with every clause anchor pointed at a clause that is not there."""
    candidates = tuple(
        replace(c, clause_anchor=c.clause_anchor + "-bogus") for c in result.candidates
    )
    return replace(result, candidates=candidates)


def flag_present(case: tuple[Contract, ExtractionResult, str, RiskFlag]) -> float:
    """1.0 when the named clause's admitted row carries the expected flag, else 0.0."""
    contract, result, clause_number, flag = case
    admission = admit_contract(contract, result, as_of=AS_OF)
    for row in admission.rows:
        if row.clause_number == clause_number:
            return 1.0 if flag in row.flags else 0.0
    return 0.0


def linkage_ratio(case: tuple[Contract, ExtractionResult, int]) -> float:
    """Fraction of the expected obligations that admit with a real clause link."""
    contract, result, expected = case
    admission = admit_contract(contract, result, as_of=AS_OF)
    if expected == 0:
        return 1.0
    return len(admission.rows) / expected


def test_flag_classification_can_go_red_per_family() -> None:
    cases: dict[str, tuple[object, object]] = {}
    for family, (contract_id, clause_number, flag) in _FLAG_WITNESS.items():
        contract = _get(contract_id)
        result = proposals_for(contract_id)
        anchor = f"{contract_id}#cl-{clause_number}"
        green = (contract, result, clause_number, flag)
        red = (contract, _strip_flag(result, anchor), clause_number, flag)
        cases[family] = (green, red)
    assert_each_can_go_red(flag_present, cases, threshold=1.0, metric="flag_present")


def test_clause_linkage_can_go_red_per_contract_family() -> None:
    cases: dict[str, tuple[object, object]] = {}
    for contract_id in _CONTRACTS:
        contract = _get(contract_id)
        result = proposals_for(contract_id)
        expected = len(admit_contract(contract, result, as_of=AS_OF).rows)
        green = (contract, result, expected)
        red = (contract, _corrupt_anchors(result), expected)
        cases[contract] = (green, red)
    assert_each_can_go_red(linkage_ratio, cases, threshold=1.0, metric="linkage_ratio")
