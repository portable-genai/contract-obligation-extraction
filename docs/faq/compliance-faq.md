# Compliance FAQ

For compliance, legal operations and model risk. The mapping table with a file reference on every
row is [`../../COMPLIANCE.md`](../../COMPLIANCE.md); this page answers the questions that come
back after reading it.

### If this system says clause 7.2 creates an obligation, can we prove it?

Yes, and that traceability is the vertical's core guarantee rather than a feature.
`domain/clauses.py` segments the document into clauses with STABLE anchor ids, and every extracted
obligation, date and risk flag carries the anchor it came from. Stability is the load-bearing
part: an anchor that moved when the document was re-read would make every citation unverifiable a
month later.

### A model read the contract. How is the register still defensible?

Because the model can only PROPOSE. The determinism rule is written into `domain/flags.py`: the
model classifies a clause, and code decides whether the classification is admissible against a
frozen taxonomy. Three consequences a reviewer can check:

- a proposed flag outside the taxonomy is DROPPED, never coerced to the nearest known one;
- a proposal the model marked ambiguous is ROUTED to a human, never defaulted to present or
  absent;
- no date arithmetic is ever the model's. `domain/renewals.py` computes renewal and deadline
  clocks over the shared kernel's primitives with an explicit `as_of` and no system clock, so a
  register is replayable.

### Who signs off?

A human, always, for anything consequential, and in this vertical that includes every ambiguous
flag proposal. `requires_human_review` and the call to `ReviewRouterPort.route` are one act, not a
flag plus an intention: the API, the CLI and the agent tools all route in the same call that
produced the result, and `tests/unit/test_review_routing.py` asserts the routing rather than the
flag. Under the managed profile the router REFUSES when no console is configured.

### Where does the data live, and is residency enforced or just documented?

Enforced at deploy time for everything this stack creates. The region is chosen once
(`asia-southeast1`) and shared by the runtime and Terraform: `infra/terraform/variables.tf`
validates the region against the residency allowlist at plan, `org_policy.tf` pins
`gcp.resourceLocations` to that region's location group, and every regional resource (the CMEK key
ring, the WORM log bucket, the Cloud Run service) is created in it.
`infra/terraform/production_edge.tftest.hcl` is the standing proof, running against a mocked
provider so it needs no project and no credentials.

What this stack does NOT create, and therefore cannot pin, is the document source. Contracts are
among the most residency-sensitive documents a bank holds, so where they live, and where the
extraction service reads them from, is the first residency question to settle rather than the
last.

### What about key management and least privilege?

One REGIONAL CMEK key with a 90-day rotation, and an explicit key binding for EACH service agent
that encrypts under it, because CMEK does not cascade (`infra/terraform/kms.tf`). One serving
identity holding only the roles a request needs, each traceable to a bound adapter, with
`logging.logWriter` write only so the process cannot read back the WORM trail it writes
(`iam.tf`). Exportable service-account keys are forbidden by org policy rather than merely
avoided, and a key creation raises an alert if one happens anyway.

### How long is the audit trail kept, and can it be edited?

180 days by default, and the variable refuses anything below 180. The Cloud Logging bucket is
LOCKED by default, which is irreversible: once applied, retention cannot be reduced and the bucket
cannot be deleted for the full window, not even with project-owner rights. Confirm
`retention_days` before the first apply, and set it against your contract-retention standard
rather than the default: obligations outlive the contracts that created them, and the lock cannot
be loosened afterwards. DATA_READ audit logging is enabled too, so a read of a register is itself
recorded.

Offline the same guarantee is earned differently: the log is hash-chained AND externally anchored,
because a truncated tail leaves a shorter chain that verifies perfectly.

### What personal data does this system process?

Contracts carry counterparty names, signatory names and contact details. Redaction runs before
every boundary rather than once at the end: before the audit write, before the outbound review
payload, and before any tool result that could enter a model's context. The jurisdiction rows and
their ORDER are chosen in `domain/pii.py`. The `pii_safety` metric holds this at `>= 0.99` and is
proved able to go red.

### What model-risk evidence exists?

[`../model-card.md`](../model-card.md) records both model seams and their very different states:
narration is wired and bounded (schema plus groundedness check, deterministic fallback), and
extraction is a DECLARED seam that raises rather than a working client, so the managed document
path has never run. What is NOT yet in place for either: a confirmed model id and version, a token
budget, a rate limit, a kill switch, a live-model eval run registered with the `model-quality-gate` promotion
gate, and prompt-injection screening through `agent-guardrail-gateway`. That last one is the highest-priority item for
this repo specifically, because a contract is untrusted text written by a counterparty.

### Which regulations does this claim to satisfy?

None, on your behalf. The mapping in `COMPLIANCE.md` is to the CATALOG's own principles (P-01 to
P-13) and platform rules (R1 to R8). The crosswalk from those to MAS TRM, CPS 234, CPS 230, HKMA
or PDPA control ids, and the judgement that a control is SUFFICIENT for a regulation, is
explicitly adopter-owned. No row should be quoted as regulatory assurance, and the second-line
review of the risk-flag taxonomy is bank-owned policy rather than a vendor default to inherit
unexamined. Nothing this system produces is legal advice or a legal opinion on a contract.

### What is still open at go-live?

The `Partial` and `TODO (repo owner)` rows in `COMPLIANCE.md`, each of which names exactly what is
missing. The ones that need a risk acceptance if you go live without them: the managed extraction
adapter, rule R1 (the `agent-guardrail-gateway` binding in front of it), rule R5 and P-08 (the `model-quality-gate` metric
bundle), P-10 (timeouts, circuit breaker and a documented kill switch), the document source's
residency and access control, and P-01's private-egress rule.
