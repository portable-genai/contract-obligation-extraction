# Features FAQ

For a product owner, a legal-operations lead or a delivery manager deciding what this system does,
what it refuses to do, and where its responsibility ends.

### What does it actually do?

It turns a contract into a tracked register, in steps that are deterministic except for the one
step that reads prose:

1. **Segment** (`domain/clauses.py`): the document becomes clauses with STABLE anchor ids. This
   is the load-bearing guarantee of the whole vertical, because every obligation, date and risk
   flag links back to the exact clause it came from, and that link is only worth anything if the
   anchor does not move when the document is re-read.
2. **Propose** (`ExtractionPort`): the model reads the clauses and proposes obligations, dates and
   flag classifications. This is the only step a model contributes to.
3. **Admit or refuse** (`domain/flags.py`, `domain/contracts.py`): code decides which proposals
   are admissible against a frozen taxonomy. A proposed flag outside the taxonomy is DROPPED,
   never coerced to the nearest known one; a proposal the model marked ambiguous is ROUTED to a
   human, never defaulted to present or absent.
4. **Compute the clocks** (`domain/renewals.py`): renewal and deadline maths over the shared
   kernel's primitives, with an explicit `as_of` and no system clock, so a register is replayable.
5. **Narrate** (`domain/narration.py`): a short register summary that restates the engine's
   figures and adds none.

### What is the determinism rule, exactly?

"The model CLASSIFIES a clause; code DECIDES whether the classification is admissible." A model
may propose that clause 7 is a liability cap. Which flags exist, how severe each is, and whether
an ambiguous proposal is admitted or held for review are all decided by `domain/flags.py` against
a frozen taxonomy. Nothing the model returns becomes a register entry without passing that gate,
and no date arithmetic is ever the model's.

### What is the model allowed to say in the summary?

Only figures the engine produced. `domain/narration.py` holds the summary to two hard rules:
schema validation, so malformed output is discarded rather than repaired, and groundedness, so a
summary that invents a figure is discarded and a deterministic summary built from the engine's own
facts is used instead. The `narration_groundedness` eval metric holds this at `>= 0.99`. See
[`../model-card.md`](../model-card.md).

### What will it refuse to do?

- **It will not admit a flag it does not recognise.**
- **It will not resolve an ambiguous proposal on its own.**
- **It will not produce a date the engine did not compute.**
- **It will not auto-execute a consequential result.** A consequential register sets
  `requires_human_review` and is ROUTED to Hrz7 in the same call that produced it (rule R8).
- **It will not answer without provenance.** Every entry carries the clause anchor it came from.

### Which surfaces expose it?

The FastAPI app (`POST /v1/register` for a corpus contract's register, `POST /v1/triage` for the
single-case decision), the argparse CLI (`register` and `triage`), the agent tools (advertised on
the A2A card at `/.well-known/agent-card.json`), the embeddable `ui/` micro-frontend, and the eval
harness. Each routes escalations in the same call.

Note that the repo carries the template's generic triage service (`domain/triage_service.py`,
`/v1/triage`) alongside the contract vertical. The register path is the reason this system exists.

### Who consumes the register?

**Rgc8**, the third-party risk and DDQ system, for the contractual terms behind a vendor's
inherent and residual risk rating. Because Rgc8 was not built when this feed was designed, the
wire shape is frozen as a recorded PROPOSAL rather than an agreement, and it is documented in
[`../rgc8-feed.md`](../rgc8-feed.md). It is not a bespoke serialiser: it is the shared kernel's
envelope over a register snapshot
(`obligation_register.schema.envelope("contract_obligation_register", ...)`), and
`tests/unit/test_contracts.py::test_the_rgc8_feed_carries_a_schema_version` holds the shape and
version stable so a later change is deliberate and reviewed.

### What does this repo own, and what does it integrate?

| Concern | Owner | How this repo touches it |
|---|---|---|
| Contract reading, the clause anchors, the obligation register per contract | **this repo (Rgc12)** | it IS the engine. |
| The canonical register serialisation and the deadline primitives | the shared `obligation-register-kit` | imported, not reimplemented. |
| Vendor inherent and residual risk | **Rgc8** third-party risk and DDQ | consumes this register through the frozen feed. |
| The firm-wide obligation to control graph | **Rgc7** obligations and control mapping | a contract register is a source that can feed it, not a second copy of it. |
| Agent discovery and entitlements | **Hrz3** agent registry | this agent publishes a card; the registry owns discovery. |
| Model and agent promotion | **Hrz4** AI quality and model risk | `eval/run_eval.py --mode gate` asks Hrz4; the offline smoke mode never promotes. |
| Traces and the immutable audit sink | **Hrz5** agent observability | `AuditSinkPort` and `ObservabilityTracerPort`. |
| Human review and maker-checker | **Hrz7** human review console | `ReviewRouterPort` over the shared `review-kit`. Every ambiguous flag proposal lands here. |
| Prompt-injection defence and output filtering | **Hrz1** agent guardrail gateway | **not wired today, and this repo needs it most.** A contract is untrusted third-party text that reaches a model (rule R1). |
| Grounded retrieval over an enterprise corpus | **Hrz2** enterprise knowledge base | not wired; the document itself is the context. |

### Can I demo it without a cloud project?

Yes, and the demo is code rather than a deck. The offline profile ships five obviously fictional
contracts (MSA, SOW, DPA, outsourcing, ISDA) in `domain/corpus.py` together with the canned
extractor proposals it replays, so the whole arc runs with no model. `make demo` is the
presenter-paced walkthrough, `make demo-selftest` runs the same arc headless and asserts every
narrated claim, and `make demo-static` renders the audit-first panels to static HTML for
screenshots.

### What is not built yet?

The honest list is [`../practices-audit.md`](../practices-audit.md) and the `TODO (repo owner)`
rows in [`../../COMPLIANCE.md`](../../COMPLIANCE.md). The three that matter most: the managed
`ExtractionPort` adapter is a declared seam that raises rather than a working Document AI client,
the Hrz1 guardrail is not bound in front of it, and this repo's metric bundle is not registered
with Hrz4.
