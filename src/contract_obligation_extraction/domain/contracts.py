"""The contract-obligation vertical: the deterministic engine, over obligation-register-kit.

This is Rgc12's reason to exist: read an executed or draft contract and produce a tracked,
owner-assigned, deadline-bearing REGISTER of obligations, key clauses, dates and risk flags, each
linked to the exact clause it came from. The consequential work is PURE CODE: clause segmentation
gives every clause a stable anchor (``clauses.py``); admission refuses any candidate whose cited
anchor is not real and dedups on the shared kernel key; the risk-flag taxonomy validates every
proposed flag and drops the unknown ones; the renewal clock decides what is breached or inside its
notice window (``renewals.py``); and the severity band is a pure function of the admitted flags and
deadlines. The model (behind the extraction port) only READS and PROPOSES; it never decides which
anchor is real, which flag is admissible, or how severe the picture is.

The kit supplies the shared model: an :class:`~obligation_register.Obligation` carries its
:class:`~obligation_register.Citation`, ``admit`` dedups a batch, and a
:class:`~obligation_register.Register` pins versioned, effective-dated snapshots so the register
this repo feeds to Rgc8 carries a schema version from day one. These are the SAME
admission rules Rgc7 applies to a regulatory corpus, pointed here at a contractual one.

Pure stdlib plus the stdlib-only kernel: no web framework, no cloud SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from obligation_register import (
    Citation,
    Deadline,
    Obligation,
    ObligationGraph,
    Register,
    RegisterSnapshot,
    admit,
    envelope,
)

from ..ports.audit import AuditSinkPort
from ..ports.extraction import ExtractionResult, ProposedObligation
from .clauses import Clause, clause_by_anchor, segment_clauses
from .flags import DEFAULT_TAXONOMY, FlagTaxonomy, RiskFlag, flag_from_value
from .kernel import AuditEvent, Decision, Severity, utcnow
from .kernel import Citation as AuditCitation
from .renewals import DEFAULT_RENEWAL_POLICY, DeadlineView, RenewalPolicy, deadline_view

__all__ = [
    "Contract",
    "ContractFamily",
    "ContractObligation",
    "ContractRegister",
    "CrossTenantError",
    "RegisterService",
    "admit_contract",
    "authorize_contract_access",
    "register_envelope",
    "register_severity",
]


class ContractFamily(StrEnum):
    """The contract families this engine reads (the closed corpus vocabulary)."""

    MSA = "msa"  # master services agreement
    SOW = "sow"  # statement of work
    DPA = "dpa"  # data processing agreement
    OUTSOURCING = "outsourcing"  # material outsourcing / cloud agreement
    ISDA = "isda"  # ISDA master agreement / derivatives


@dataclass(frozen=True, slots=True)
class Contract:
    """One executed or draft contract: identity, family, counterparty and its clause body.

    ``tenant`` is the owning partition: the register is authorised against the verified
    principal's tenant, so a caller from another tenant is refused (403, never 404).
    ``effective_from`` dates the register snapshot. All parties are obviously fictional.
    """

    contract_id: str
    family: ContractFamily
    counterparty: str
    title: str
    body: str
    tenant: str = "demo-bank"
    effective_from: date = date(2026, 1, 1)
    governing_law: str = ""

    def clauses(self) -> tuple[Clause, ...]:
        """The deterministic clause segmentation of this contract (stable anchors)."""
        return segment_clauses(self.contract_id, self.body)


class CrossTenantError(Exception):
    """A verified principal asked for a contract owned by a different tenant.

    Mapped to HTTP 403, never 404: the contract EXISTS and the caller is simply not authorised.
    A 404 would both misdescribe the refusal and leak the same fact more quietly, and because the
    authorisation is against the VERIFIED principal, a 403 discloses nothing a truthful boundary
    does not already imply.
    """

    def __init__(self, principal_tenant: str, contract_tenant: str) -> None:
        super().__init__(
            f"tenant {principal_tenant!r} is not authorised for a contract owned by "
            f"{contract_tenant!r}"
        )
        self.principal_tenant = principal_tenant
        self.contract_tenant = contract_tenant


def authorize_contract_access(principal_tenant: str, *, contract_tenant: str) -> None:
    """Authorise a VERIFIED principal's tenant against the contract's owning tenant.

    Returns ``None`` when the tenants match; raises :class:`CrossTenantError` otherwise. There is
    deliberately no permissive default for ``principal_tenant``: the caller passes the value it
    resolved from the verified principal, never a fallback that would authorise an
    unauthenticated request.
    """
    if principal_tenant != contract_tenant:
        raise CrossTenantError(principal_tenant, contract_tenant)


# --------------------------------------------------------------------------- #
# The register rows and the consequential result
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ContractObligation:
    """One admitted obligation row: the obligation, its clause link, flags and deadline status.

    ``needs_review`` is the per-row escalation signal: an ambiguous classification, or a flag
    family the taxonomy marks as always-review (step-in, sub-outsourcing), or a breached
    deadline. It is a computed fact, never a default.
    """

    obligation_id: str
    text: str
    owner: str
    clause_anchor: str
    clause_number: str
    flags: tuple[RiskFlag, ...]
    deadline: DeadlineView | None
    needs_review: bool
    citation: Citation

    @property
    def flag_values(self) -> tuple[str, ...]:
        return tuple(flag.value for flag in self.flags)


@dataclass(frozen=True, slots=True)
class ContractRegister:
    """The consequential register for one contract: rows, counts, severity, provenance.

    The field set overlaps the shared review envelope (``subject`` / ``severity`` / ``decision``
    / ``summary`` / ``requires_human_review`` / ``citations``) so a surface routes it to Hrz7
    through the R8 path without the pure domain importing a surface type.
    """

    contract_id: str
    family: ContractFamily
    counterparty: str
    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    obligations: tuple[ContractObligation, ...]
    dropped: tuple[str, ...]  # candidate texts refused for an unreal or missing clause anchor
    flag_counts: tuple[tuple[str, int], ...]
    snapshot: RegisterSnapshot
    as_of: date
    citations: tuple[Citation, ...] = ()

    @property
    def counts(self) -> tuple[tuple[str, int], ...]:
        """The engine-owned register tallies, as (name, value) pairs for narration grounding."""
        deadlines = [o.deadline for o in self.obligations if o.deadline is not None]
        return (
            ("obligations", len(self.obligations)),
            ("flagged", sum(1 for o in self.obligations if o.flags)),
            ("needs_review", sum(1 for o in self.obligations if o.needs_review)),
            ("dropped", len(self.dropped)),
            ("overdue", sum(1 for d in deadlines if d.breached)),
            ("in_notice_window", sum(1 for d in deadlines if d.in_notice_window)),
        )


# --------------------------------------------------------------------------- #
# Admission: the consequential engine (pure)
# --------------------------------------------------------------------------- #
def _parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None


def _admitted_flags(candidate: ProposedObligation, taxonomy: FlagTaxonomy) -> tuple[RiskFlag, ...]:
    """Validate the candidate's proposed flags against the taxonomy, dropping the unknown ones."""
    seen: list[RiskFlag] = []
    for raw in candidate.proposed_flags:
        flag = flag_from_value(raw)
        if flag is None or not taxonomy.is_admissible(flag):
            continue  # an unknown flag is dropped, never coerced to the nearest known one
        if flag not in seen:
            seen.append(flag)
    return tuple(seen)


def _needs_review(
    candidate: ProposedObligation,
    flags: tuple[RiskFlag, ...],
    taxonomy: FlagTaxonomy,
    dv: DeadlineView | None,
) -> bool:
    """Decide whether one row must be held for a human (a computed fact, never a default)."""
    if candidate.ambiguous:
        return True
    if candidate.proposed_flags and not flags:
        # The model proposed classifications and none were admissible: an unresolved
        # classification is held for review rather than silently emptied.
        return True
    if any(taxonomy.rule_for(flag).review_always for flag in flags):
        return True
    return bool(dv and dv.breached)


@dataclass(frozen=True, slots=True)
class _Admission:
    """Internal admission outcome, before the audited result is assembled."""

    rows: tuple[ContractObligation, ...]
    dropped: tuple[str, ...]
    snapshot: RegisterSnapshot


def admit_contract(
    contract: Contract,
    result: ExtractionResult,
    *,
    as_of: date,
    taxonomy: FlagTaxonomy = DEFAULT_TAXONOMY,
    policy: RenewalPolicy = DEFAULT_RENEWAL_POLICY,
) -> _Admission:
    """Admit the extractor's candidates into a register (the consequential engine, pure).

    Each candidate is validated against the real clause segmentation: a candidate whose cited
    anchor is not one this contract produced is DROPPED, never admitted against a defaulted
    clause. Surviving candidates become kernel obligations carrying a clause citation; ``admit``
    dedups them by content key; and the admitted set is pinned as a versioned, effective-dated
    register snapshot. Flags and deadline status are attached per row.
    """
    index = clause_by_anchor(contract.clauses())
    obligations: list[Obligation] = []
    meta: dict[str, tuple[ProposedObligation, Clause, tuple[RiskFlag, ...]]] = {}
    dropped: list[str] = []

    for seq, candidate in enumerate(result.candidates):
        clause = index.get(candidate.clause_anchor)
        if clause is None:
            dropped.append(candidate.text)
            continue  # uncited or fabricated anchor: dropped, not defaulted
        flags = _admitted_flags(candidate, taxonomy)
        due = _parse_iso(candidate.due_on) if candidate.due_on else None
        deadline = (
            Deadline(due_on=due, kind=candidate.due_kind or "obligation")
            if due is not None
            else None
        )
        obligation = Obligation(
            id=f"{contract.contract_id}:{clause.number}:{seq}",
            title=clause.heading or clause.number,
            text=candidate.text,
            owner=candidate.owner,
            citation=Citation(
                source_id=contract.contract_id,
                locator=clause.number,
                title=clause.heading or contract.title,
                snippet=clause.text[:160],
            ),
            effective_from=contract.effective_from,
            deadline=deadline,
        )
        obligations.append(obligation)
        meta[obligation.id] = (candidate, clause, flags)

    outcome = admit(ObligationGraph(), obligations)
    register = Register().append(outcome.graph, effective_from=contract.effective_from)
    snapshot = register.latest
    assert snapshot is not None  # a register appended once always has a head

    rows: list[ContractObligation] = []
    for obligation in outcome.admitted:
        candidate, clause, flags = meta[obligation.id]
        dv = (
            deadline_view(
                obligation.id,
                obligation.deadline.due_on,
                obligation.deadline.kind,
                candidate.notice_days,
                as_of,
                policy,
            )
            if obligation.deadline is not None
            else None
        )
        rows.append(
            ContractObligation(
                obligation_id=obligation.id,
                text=obligation.text,
                owner=obligation.owner,
                clause_anchor=clause.anchor,
                clause_number=clause.number,
                flags=flags,
                deadline=dv,
                needs_review=_needs_review(candidate, flags, taxonomy, dv),
                citation=obligation.citation,
            )
        )
    return _Admission(rows=tuple(rows), dropped=tuple(dropped), snapshot=snapshot)


def register_severity(rows: tuple[ContractObligation, ...]) -> Severity:
    """The deterministic severity band for a whole register (pure; the model never produces it).

    The worst admitted flag severity, lifted to HIGH if any deadline is breached; LOW when the
    register carries no flag and no breach. The bands themselves are the taxonomy's (config-owned,
    practices check B4).
    """
    order = (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
    worst = Severity.LOW
    for row in rows:
        for flag in row.flags:
            severity = DEFAULT_TAXONOMY.severity_of(flag)
            if order.index(severity) > order.index(worst):
                worst = severity
        if (
            row.deadline is not None
            and row.deadline.breached
            and order.index(Severity.HIGH) > order.index(worst)
        ):
            worst = Severity.HIGH
    return worst


def register_envelope(register: ContractRegister) -> dict[str, object]:
    """The versioned wire shape for the Rgc8 feed: the kernel schema envelope over the snapshot.

    Rgc8 consumes this per-contract register, so it carries an explicit
    ``schema_version`` from day one (the kernel stamps it). Until Rgc8 exists this shape is a
    recorded PROPOSAL, frozen by a contract test, not an agreement.
    """
    return envelope("contract_obligation_register", register.snapshot)


# --------------------------------------------------------------------------- #
# The audited service (redact-before-audit, cited, soft-escalating)
# --------------------------------------------------------------------------- #
class RegisterService:
    """Assemble a contract's obligation register into a consequential, cited, audited result.

    Mirrors the reference service shape: the decision is deterministic (segmentation, admission,
    the taxonomy and the renewal clock), an already-redacted audit record is written before the
    result is returned, every result is cited, and a register carrying any material finding
    escalates to a human (routed under rule R8 by the calling surface).
    """

    def __init__(self, audit: AuditSinkPort) -> None:
        self._audit = audit

    def build(
        self,
        contract: Contract,
        result: ExtractionResult,
        *,
        as_of: date,
        actor: str,
        taxonomy: FlagTaxonomy = DEFAULT_TAXONOMY,
        policy: RenewalPolicy = DEFAULT_RENEWAL_POLICY,
    ) -> ContractRegister:
        admission = admit_contract(contract, result, as_of=as_of, taxonomy=taxonomy, policy=policy)
        rows = admission.rows
        severity = register_severity(rows)
        requires_review = any(row.needs_review for row in rows) or any(row.flags for row in rows)
        decision = Decision.ESCALATED if requires_review else Decision.ALLOWED
        flag_counts = _flag_counts(rows)
        subject = f"{contract.family.value}:{contract.counterparty}"
        summary = _summary(contract, rows, admission.dropped)
        citations = tuple(row.citation for row in rows[:8]) or (
            Citation(source_id=contract.contract_id, locator="", title=contract.title),
        )

        # Redact before the audit write. The summary is engine-derived, but the rule is
        # unconditional: nothing reaches a WORM record that did not pass the audit envelope.
        self._audit.record(
            AuditEvent(
                action="contract_register",
                actor=actor,
                decision=decision,
                severity=severity,
                redacted_summary=summary,
                citations=tuple(_to_audit_citation(c) for c in citations[:4]),
                timestamp=utcnow(),
            )
        )

        return ContractRegister(
            contract_id=contract.contract_id,
            family=contract.family,
            counterparty=contract.counterparty,
            subject=subject,
            severity=severity,
            decision=decision,
            summary=summary,
            requires_human_review=requires_review,
            obligations=rows,
            dropped=admission.dropped,
            flag_counts=flag_counts,
            snapshot=admission.snapshot,
            as_of=as_of,
            citations=citations,
        )


def _flag_counts(rows: tuple[ContractObligation, ...]) -> tuple[tuple[str, int], ...]:
    tally: dict[str, int] = {flag.value: 0 for flag in RiskFlag}
    for row in rows:
        for flag in row.flags:
            tally[flag.value] += 1
    return tuple(sorted(tally.items()))


def _summary(
    contract: Contract, rows: tuple[ContractObligation, ...], dropped: tuple[str, ...]
) -> str:
    flagged = sum(1 for row in rows if row.flags)
    review = sum(1 for row in rows if row.needs_review)
    return (
        f"{contract.family.value}/{contract.counterparty}: obligations={len(rows)}; "
        f"flagged={flagged}; needs_review={review}; dropped={len(dropped)}"
    )


def _to_audit_citation(citation: Citation) -> AuditCitation:
    """Translate a kernel (kit) citation into the audit/review envelope citation type."""
    return AuditCitation(
        source_id=citation.source_id,
        title=citation.title or citation.locator or citation.source_id,
        snippet=citation.snippet or citation.locator,
    )
