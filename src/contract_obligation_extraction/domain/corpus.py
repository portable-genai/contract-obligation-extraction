"""The offline contract corpus and the canned extractor proposals (obviously fictional).

This is the system-under-demo content: five fictional contracts, one per family the catalog row
names (MSA, SOW, DPA, outsourcing, ISDA), plus the deterministic "model output" the local
extraction adapter replays for each. Keeping the contracts and their proposals in one module means
the clause anchors the proposals cite are the SAME anchors the segmentation produces, so the
offline pipeline, the eval oracle and the demo all reason over one coherent set.

Every party, counterparty, instrument and identifier here is invented. Domains are ``.example``;
all obligations, dates and clause text are fictional and carry no real contractual meaning.

The proposals deliberately exercise every path the engine must handle: valid flagged obligations,
a renewal with a live notice window, an OVERDUE renewal notice (the breach path), an always-review
step-in / sub-outsourcing right, a candidate the model marked AMBIGUOUS, a candidate whose proposed
flag is OUTSIDE the taxonomy (dropped classification, held for review), a DUPLICATE that dedups
away, and a candidate citing a clause anchor that does not exist (dropped, never defaulted).
"""

from __future__ import annotations

from datetime import date

from ..ports.extraction import ExtractionResult, ProposedObligation
from .contracts import Contract, ContractFamily

__all__ = [
    "AS_OF",
    "SEED_CONTRACTS",
    "contract_by_id",
    "proposals_for",
]

#: The frozen reference date the demo and the eval evaluate against. Every deadline below is
#: positioned relative to it so the "breached", "in notice window" and "upcoming" cases are stable.
AS_OF = date(2026, 6, 1)


# --------------------------------------------------------------------------- #
# The contracts (numbered clauses; segmentation derives one anchor per number)
# --------------------------------------------------------------------------- #
_MSA_BODY = """This Master Services Agreement is made between Northwind Bank (FICTIONAL) and
Meridian Cloud Services Pte Ltd (FICTIONAL).

1. Term and Termination
This Agreement commences on the Effective Date and renews annually unless the Provider gives the
Customer no less than 90 days written notice before the renewal date of 1 August 2026.

2. Fees
The Customer shall pay the fees set out in Schedule B within thirty days of each invoice.

3. Limitation of Liability
The Provider's aggregate liability under this Agreement is capped at the fees paid in the
preceding twelve months.

4. Indemnification
The Provider shall indemnify the Customer against third-party claims of intellectual property
infringement arising from the services.

5. Audit Rights
The Customer may audit the Provider's controls on thirty days notice, no more than once per year.

6. Subcontracting
The Provider shall not subcontract any material part of the services without the Customer's prior
written consent.
"""

_SOW_BODY = """This Statement of Work is issued under the Master Services Agreement between
Northwind Bank (FICTIONAL) and Meridian Cloud Services Pte Ltd (FICTIONAL).

1. Scope of Work
The Provider shall perform the migration services described in Schedule A.

2. Deliverables
The Provider shall deliver the migration runbook to the Customer by 15 December 2026.

3. Acceptance
The Customer shall have ten business days to accept each deliverable.
"""

_DPA_BODY = """This Data Processing Agreement supplements the Master Services Agreement between
Northwind Bank (FICTIONAL) as Controller and Meridian Cloud Services Pte Ltd (FICTIONAL) as
Processor.

1. Data Residency
The Processor shall store and process personal data only within Singapore.

2. Sub-processing
The Processor shall not engage any sub-processor without the Controller's prior written
authorisation.

3. Audit Rights
The Controller may audit the Processor's data-protection controls once per calendar year.

4. Breach Notification
The Processor shall notify the Controller of a personal data breach within 72 hours of becoming
aware of it.

5. Cross-border Transfer
The Processor may transfer personal data outside Singapore only under an approved transfer
mechanism.
"""

_OUTSOURCING_BODY = """This Material Outsourcing Agreement is made between Northwind Bank
(FICTIONAL) and Apex Managed Operations Ltd (FICTIONAL).

1. Term and Renewal
This Agreement renews for successive one-year terms unless the Bank gives at least 60 days notice
before the renewal date of 15 May 2026.

2. Step-in Rights
The Bank and its regulator may step in to operate the outsourced service on notice where
continuity is threatened.

3. Sub-outsourcing
The Service Provider shall not sub-outsource any material function without the Bank's approval.

4. Service Levels
The Service Provider shall maintain at least 99.9% monthly availability of the outsourced service.

5. Liability
The Service Provider's liability is capped at the charges paid in the preceding twelve months.
"""

_ISDA_BODY = """This ISDA Master Agreement is made between Northwind Bank (FICTIONAL) and Global
Derivatives Counterparty LLC (FICTIONAL).

1. Termination Events
Either party may designate an Early Termination Date following an Event of Default by the other
party.

2. Payment Netting
Payments in the same currency and due on the same date shall be netted and settled by 11:00 on the
value date.

3. Credit Support
Each party shall post variation margin in accordance with the Credit Support Annex.

4. Indemnity
Each party shall indemnify the other for reasonable costs incurred in enforcing its rights after a
default.
"""


SEED_CONTRACTS: tuple[Contract, ...] = (
    Contract(
        contract_id="meridian-msa-2026",
        family=ContractFamily.MSA,
        counterparty="Meridian Cloud Services Pte Ltd (FICTIONAL)",
        title="Master Services Agreement",
        body=_MSA_BODY,
        governing_law="Singapore",
    ),
    Contract(
        contract_id="meridian-sow-014",
        family=ContractFamily.SOW,
        counterparty="Meridian Cloud Services Pte Ltd (FICTIONAL)",
        title="Statement of Work 014",
        body=_SOW_BODY,
        governing_law="Singapore",
    ),
    Contract(
        contract_id="meridian-dpa-2026",
        family=ContractFamily.DPA,
        counterparty="Meridian Cloud Services Pte Ltd (FICTIONAL)",
        title="Data Processing Agreement",
        body=_DPA_BODY,
        governing_law="Singapore",
    ),
    Contract(
        contract_id="apex-outsourcing-2026",
        family=ContractFamily.OUTSOURCING,
        counterparty="Apex Managed Operations Ltd (FICTIONAL)",
        title="Material Outsourcing Agreement",
        body=_OUTSOURCING_BODY,
        governing_law="Singapore",
    ),
    Contract(
        contract_id="global-isda-2026",
        family=ContractFamily.ISDA,
        counterparty="Global Derivatives Counterparty LLC (FICTIONAL)",
        title="ISDA Master Agreement",
        body=_ISDA_BODY,
        governing_law="England and Wales",
    ),
)

_BY_ID = {contract.contract_id: contract for contract in SEED_CONTRACTS}


def _anchor(contract_id: str, number: str) -> str:
    return f"{contract_id}#cl-{number}"


# --------------------------------------------------------------------------- #
# The canned model proposals (what the local ExtractionPort replays per contract)
# --------------------------------------------------------------------------- #
_MSA = "meridian-msa-2026"
_SOW = "meridian-sow-014"
_DPA = "meridian-dpa-2026"
_OUT = "apex-outsourcing-2026"
_ISDA = "global-isda-2026"


_PROPOSALS: dict[str, tuple[ProposedObligation, ...]] = {
    _MSA: (
        ProposedObligation(
            text="Provider gives at least 90 days written notice before the 1 August 2026 renewal.",
            clause_anchor=_anchor(_MSA, "1"),
            owner="vendor-management",
            due_on="2026-08-01",
            due_kind="renewal_notice",
            notice_days=90,
            proposed_flags=("termination_renewal",),
        ),
        ProposedObligation(
            text="Provider aggregate liability is capped at fees paid in the preceding 12 months.",
            clause_anchor=_anchor(_MSA, "3"),
            owner="legal",
            proposed_flags=("liability_cap",),
        ),
        # A duplicate of the liability obligation (same text and owner): dedups away in admission.
        ProposedObligation(
            text="Provider aggregate liability is capped at fees paid in the preceding 12 months.",
            clause_anchor=_anchor(_MSA, "3"),
            owner="legal",
            proposed_flags=("liability_cap",),
        ),
        ProposedObligation(
            text="Provider indemnifies Customer against third-party IP infringement claims.",
            clause_anchor=_anchor(_MSA, "4"),
            owner="legal",
            proposed_flags=("indemnity",),
        ),
        ProposedObligation(
            text="Customer may audit Provider controls on 30 days notice, once per year.",
            clause_anchor=_anchor(_MSA, "5"),
            owner="internal-audit",
            proposed_flags=("audit_step_in",),
        ),
        ProposedObligation(
            text="Provider shall not subcontract material services without prior written consent.",
            clause_anchor=_anchor(_MSA, "6"),
            owner="vendor-management",
            proposed_flags=("sub_outsourcing",),
        ),
        # A fabricated clause anchor (there is no clause 9): dropped, never defaulted.
        ProposedObligation(
            text="Provider warrants uptime of 100% at all times.",
            clause_anchor=_anchor(_MSA, "9"),
            owner="service-management",
            proposed_flags=("sla_commitment",),
        ),
    ),
    _SOW: (
        ProposedObligation(
            text="Provider performs the migration services described in Schedule A.",
            clause_anchor=_anchor(_SOW, "1"),
            owner="delivery-lead",
        ),
        ProposedObligation(
            text="Provider delivers the migration runbook by 15 December 2026.",
            clause_anchor=_anchor(_SOW, "2"),
            owner="delivery-lead",
            due_on="2026-12-15",
            due_kind="deliverable",
        ),
    ),
    _DPA: (
        ProposedObligation(
            text="Processor stores and processes personal data only within Singapore.",
            clause_anchor=_anchor(_DPA, "1"),
            owner="dpo",
            proposed_flags=("data_residency",),
        ),
        ProposedObligation(
            text="Processor engages no sub-processor without the Controller's authorisation.",
            clause_anchor=_anchor(_DPA, "2"),
            owner="dpo",
            proposed_flags=("sub_outsourcing",),
        ),
        ProposedObligation(
            text="Controller may audit the Processor's data-protection controls annually.",
            clause_anchor=_anchor(_DPA, "3"),
            owner="dpo",
            proposed_flags=("audit_step_in",),
        ),
        ProposedObligation(
            text="Processor notifies Controller of a personal data breach within 72 hours.",
            clause_anchor=_anchor(_DPA, "4"),
            owner="dpo",
            proposed_flags=("sla_commitment",),
        ),
        # The model proposed a flag OUTSIDE the taxonomy: it is dropped and the row is held for
        # review as an unresolved classification (never coerced to the nearest known flag).
        ProposedObligation(
            text="Processor transfers personal data abroad only under an approved mechanism.",
            clause_anchor=_anchor(_DPA, "5"),
            owner="dpo",
            proposed_flags=("cross_border_transfer",),
        ),
    ),
    _OUT: (
        # An OVERDUE renewal notice (due 15 May 2026, before the 1 June as_of): breached, the
        # "auto-renew a contract we meant to exit" scenario, so it escalates.
        ProposedObligation(
            text="Bank gives at least 60 days notice before the 15 May 2026 renewal date.",
            clause_anchor=_anchor(_OUT, "1"),
            owner="cro-office",
            due_on="2026-05-15",
            due_kind="renewal_notice",
            notice_days=60,
            proposed_flags=("termination_renewal",),
        ),
        ProposedObligation(
            text="Bank and regulator may step in to operate the service if continuity is at risk.",
            clause_anchor=_anchor(_OUT, "2"),
            owner="operational-resilience",
            proposed_flags=("audit_step_in",),
        ),
        ProposedObligation(
            text="Service Provider does not sub-outsource a material function without approval.",
            clause_anchor=_anchor(_OUT, "3"),
            owner="vendor-management",
            proposed_flags=("sub_outsourcing",),
        ),
        ProposedObligation(
            text="Service Provider maintains at least 99.9% monthly availability.",
            clause_anchor=_anchor(_OUT, "4"),
            owner="service-management",
            proposed_flags=("sla_commitment",),
        ),
        ProposedObligation(
            text="Service Provider liability is capped at charges paid in the preceding 12 months.",
            clause_anchor=_anchor(_OUT, "5"),
            owner="legal",
            proposed_flags=("liability_cap",),
        ),
    ),
    _ISDA: (
        ProposedObligation(
            text="Either party may designate an Early Termination Date after an Event of Default.",
            clause_anchor=_anchor(_ISDA, "1"),
            owner="legal",
            proposed_flags=("termination_renewal",),
        ),
        ProposedObligation(
            text="Same-currency, same-date payments are netted and settled by 11:00 on value date.",
            clause_anchor=_anchor(_ISDA, "2"),
            owner="operations",
            proposed_flags=("sla_commitment",),
        ),
        # The model was unsure whether the margin clause carries an obligation: marked ambiguous,
        # so the engine holds it for review rather than defaulting it either way.
        ProposedObligation(
            text="Each party posts variation margin under the Credit Support Annex.",
            clause_anchor=_anchor(_ISDA, "3"),
            owner="collateral-management",
            ambiguous=True,
        ),
        ProposedObligation(
            text="Each party indemnifies the other for costs of enforcing rights after a default.",
            clause_anchor=_anchor(_ISDA, "4"),
            owner="legal",
            proposed_flags=("indemnity",),
        ),
    ),
}


def contract_by_id(contract_id: str) -> Contract | None:
    """The seed contract with this id, or ``None`` if the corpus does not carry it."""
    return _BY_ID.get(contract_id)


def proposals_for(contract_id: str) -> ExtractionResult:
    """The canned extractor proposals for a seed contract (the local adapter's replay).

    A contract the corpus does not know returns an empty result rather than raising: the local
    adapter is a fixture, and an unknown contract is simply one it has no canned reading for.
    """
    return ExtractionResult(
        candidates=_PROPOSALS.get(contract_id, ()),
        model="local-fixture",
    )
