"""Canonical synthetic cases, shared by the unit and contract suites.

Every party is obviously fictional and every address is an ``.example`` domain or an RFC 5737 /
RFC 3849 literal. One canonical escalating case and one canonical routine case are enough for
the contract suite: parity means the SAME request through every implementation, so the request
has to have one home rather than being retyped per test.
"""

from __future__ import annotations

from contract_obligation_extraction.domain.contracts import (
    Contract,
    ContractFamily,
)
from contract_obligation_extraction.domain.models import (
    TriageInput,
)

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: A tenant partition, so the outbound-review assertions are not all on the empty string.
TENANT = "demo-bank"

#: A case that MUST escalate: the deterministic band is HIGH, so rule R8 routing applies.
ESCALATING_CASE = TriageInput(
    subject="Acme Holdings (FICTIONAL)",
    text="urgent data breach reported by the branch",
)

#: A case that must NOT escalate: a router that manufactured a review here would be lying.
ROUTINE_CASE = TriageInput(
    subject="Beta Trading (FICTIONAL)",
    text="routine note about a stationery order",
)

#: A planted identifier, so a redaction assertion has an independent literal to look for
#: rather than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: A planted address, so the same assertion has a second independent literal. ``.example`` by
#: rule: an obviously fictional domain that can never resolve to a real mailbox.
PLANTED_EMAIL = "kai.tan@delta.example"

#: An escalating case that also carries personal data, for the redact-before-anything proofs.
PII_CASE = TriageInput(
    subject="Gamma LLP (FICTIONAL)",
    text=f"urgent breach, NRIC {PLANTED_NRIC} and mail ops@gamma.example on file",
)

#: The same, with the identifier in the SUBJECT rather than the body. The subject is what a
#: citation locator is built from (``case:<subject>``) and what the review payload's case_ref and
#: source_key carry, so a redaction that only watched the free text would never see this one.
PII_SUBJECT_CASE = TriageInput(
    subject=f"Gamma LLP (FICTIONAL) for NRIC {PLANTED_NRIC}",
    text="urgent breach reported by the branch",
)

#: A contract whose CLAUSE TEXT carries personal data, for the extraction-path proofs. A contract
#: is client document text end to end: the counterparty names a person and their identifier, and
#: clause 2 is the notices clause every real agreement carries. Both identifiers are planted in
#: places a document extractor lifts verbatim.
_PII_CONTRACT_BODY = f"""This Material Outsourcing Agreement is made between Northwind Bank
(FICTIONAL) and Delta Trust Operations Pte Ltd (FICTIONAL).

1. Term and Renewal
This Agreement renews for successive one-year terms unless the Bank gives at least 60 days notice
before the renewal date of 15 May 2026.

2. Key Personnel and Notices
The Service Provider's nominated outsourcing officer is Kai Tan (NRIC {PLANTED_NRIC}) and every
notice under this Agreement shall be delivered to {PLANTED_EMAIL} within five business days.

3. Sub-outsourcing
The Service Provider shall not sub-outsource any material function without the Bank's approval.
"""

PII_CONTRACT = Contract(
    contract_id="delta-outsourcing-2026",
    family=ContractFamily.OUTSOURCING,
    counterparty=f"Delta Trust Operations Pte Ltd (FICTIONAL), attn Kai Tan {PLANTED_NRIC}",
    title="Material Outsourcing Agreement",
    body=_PII_CONTRACT_BODY,
    tenant=TENANT,
    governing_law="Singapore",
)
