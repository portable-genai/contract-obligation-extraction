"""The config-owned risk-flag taxonomy and its deterministic validation (pure stdlib).

The model CLASSIFIES a clause; this module DECIDES whether the classification is admissible. The
distinction is the whole determinism rule of the vertical: a model may propose that clause 7 is a
liability cap, but which flags exist, how severe each is, and whether an ambiguous proposal is
admitted or held for review are all decided by code against a frozen taxonomy, never by the
model. A proposed flag outside the taxonomy is dropped, never coerced to the nearest known one;
a proposal the model marked ambiguous is routed to a human, never defaulted to present or absent.

The taxonomy is a frozen policy object (practices check B4: the numbers and bands are the
client's, so they live in a dataclass a ``policy:`` block can override, not as scattered module
constants). :data:`DEFAULT_TAXONOMY` is the shipped default an offline run uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .kernel import Severity

__all__ = [
    "DEFAULT_TAXONOMY",
    "FlagRule",
    "FlagTaxonomy",
    "RiskFlag",
    "flag_from_value",
]


class RiskFlag(StrEnum):
    """The risk-flag families this engine recognises in a contract (the closed vocabulary).

    Exactly the families the catalog row names. Adding a member is a taxonomy change: it widens
    what the engine will admit, so it is a deliberate policy edit here, not a model capability.
    """

    TERMINATION_RENEWAL = "termination_renewal"
    LIABILITY_CAP = "liability_cap"
    INDEMNITY = "indemnity"
    AUDIT_STEP_IN = "audit_step_in"
    SUB_OUTSOURCING = "sub_outsourcing"
    DATA_RESIDENCY = "data_residency"
    SLA_COMMITMENT = "sla_commitment"


@dataclass(frozen=True, slots=True)
class FlagRule:
    """The policy for one flag family: how severe it is and whether it demands human review.

    ``review_always`` marks a family so material that its presence always escalates regardless of
    the surrounding contract (a step-in or sub-outsourcing right a firm must approve). The bands
    are the client's to set, which is why they live here rather than inline in the engine.
    """

    flag: RiskFlag
    severity: Severity
    review_always: bool = False


@dataclass(frozen=True, slots=True)
class FlagTaxonomy:
    """The frozen set of admissible flag rules, indexed for O(1) validation.

    Construct from a tuple of :class:`FlagRule`; the mapping is derived once. A proposed flag
    value is admissible only when it names a rule in this taxonomy, so the taxonomy is the single
    gate every model proposal passes through.
    """

    rules: tuple[FlagRule, ...]

    def rule_for(self, flag: RiskFlag) -> FlagRule:
        for rule in self.rules:
            if rule.flag is flag:
                return rule
        raise KeyError(f"no rule for flag {flag.value!r} in the taxonomy")

    def is_admissible(self, flag: RiskFlag) -> bool:
        return any(rule.flag is flag for rule in self.rules)

    def severity_of(self, flag: RiskFlag) -> Severity:
        return self.rule_for(flag).severity


def flag_from_value(value: str) -> RiskFlag | None:
    """Resolve a model-proposed flag string to a :class:`RiskFlag`, or ``None`` if unknown.

    Case- and whitespace-insensitive on the value, but it never guesses: a string that is not
    exactly one of the taxonomy's values (after normalisation) resolves to ``None`` and the
    caller drops it. There is deliberately no fuzzy match to the "nearest" flag, because a
    silently coerced flag is a fabricated classification.
    """
    normalised = value.strip().lower().replace("-", "_").replace(" ", "_")
    for flag in RiskFlag:
        if flag.value == normalised:
            return flag
    return None


#: The shipped default taxonomy (obviously a starting point; a client rebinds the bands in
#: ``config/settings.yaml`` under a ``policy:`` block). Step-in and sub-outsourcing rights always
#: escalate: they are the arrangements a regulated firm must approve before they operate.
DEFAULT_TAXONOMY = FlagTaxonomy(
    rules=(
        FlagRule(RiskFlag.TERMINATION_RENEWAL, Severity.MEDIUM),
        FlagRule(RiskFlag.LIABILITY_CAP, Severity.HIGH),
        FlagRule(RiskFlag.INDEMNITY, Severity.HIGH),
        FlagRule(RiskFlag.AUDIT_STEP_IN, Severity.HIGH, review_always=True),
        FlagRule(RiskFlag.SUB_OUTSOURCING, Severity.HIGH, review_always=True),
        FlagRule(RiskFlag.DATA_RESIDENCY, Severity.HIGH),
        FlagRule(RiskFlag.SLA_COMMITMENT, Severity.MEDIUM),
    )
)
