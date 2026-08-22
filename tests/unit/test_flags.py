"""The risk-flag taxonomy: an unknown flag is dropped, never coerced to the nearest known one.

The taxonomy is the single gate every model-proposed classification passes through, so these lock
its behaviour: a value outside the taxonomy resolves to ``None`` (the caller drops it), a
well-known value normalises case and separators, and the always-review families are marked.
"""

from __future__ import annotations

from contract_obligation_extraction.domain.flags import (
    DEFAULT_TAXONOMY,
    RiskFlag,
    flag_from_value,
)
from contract_obligation_extraction.domain.kernel import Severity


def test_a_known_flag_normalises_case_and_separators() -> None:
    assert flag_from_value("Liability-Cap") is RiskFlag.LIABILITY_CAP
    assert flag_from_value("  sub outsourcing ") is RiskFlag.SUB_OUTSOURCING


def test_an_unknown_flag_resolves_to_none_and_is_not_guessed() -> None:
    assert flag_from_value("cross_border_transfer") is None
    assert flag_from_value("liabilty_cap") is None  # a typo is not the nearest known flag


def test_every_taxonomy_flag_is_admissible_and_carries_a_severity() -> None:
    for flag in RiskFlag:
        assert DEFAULT_TAXONOMY.is_admissible(flag)
        assert isinstance(DEFAULT_TAXONOMY.severity_of(flag), Severity)


def test_step_in_and_sub_outsourcing_always_review() -> None:
    assert DEFAULT_TAXONOMY.rule_for(RiskFlag.AUDIT_STEP_IN).review_always is True
    assert DEFAULT_TAXONOMY.rule_for(RiskFlag.SUB_OUTSOURCING).review_always is True
    assert DEFAULT_TAXONOMY.rule_for(RiskFlag.LIABILITY_CAP).review_always is False
