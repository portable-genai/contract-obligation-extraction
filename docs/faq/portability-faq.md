# Portability FAQ

For architecture, cloud governance and exit planning. The question underneath all of these is
"how do we leave, and how do we know the answer is true today rather than on the day it was
written?"

### What is the lock-in surface?

Every outbound dependency is a `@runtime_checkable` Protocol in `ports/` (audit, extraction,
generation, identity, observability, review router), bound per profile from
`config/settings.yaml`. There is no cloud SDK import anywhere in `domain/`, and the managed
adapters import their SDK LAZILY inside the method, so the other two families import with no SDK
installed at all.

The one binding that would be hardest to swap is `ExtractionPort`, because Document AI plus a
long-context model is a specific capability rather than a commodity. It is worth noting that this
seam has never been wired: the managed adapter declares the model it would use and raises.

### What are the three profiles?

| Profile | What it is | Who it is for |
|---|---|---|
| `local` | SDK-free offline stack: seeded dev personas, a hash-chained SQLite WORM audit log, five fictional contracts with canned extractor proposals, a deterministic stub narrator | dev, test, CI, and the offline demo |
| `gcp` | the managed stack: IAP identity, Cloud Logging WORM, Gemini narration, and a declared (unimplemented) Document AI extraction seam | a managed deployment |
| `onprem` | fail-fast `NotImplementedError` placeholders | the sovereign exit: a client binds its own in-country implementations here |

`CONTRACT_PROFILE` selects the family. Unset means the offline adapters bind but nobody chose
them, which withdraws every relaxation rather than granting one.

### Is the portability claim tested, or just documented?

Tested, three ways, all in the offline gate or one command:

- `tests/contract/test_port_parity.py` asserts set equality across all five homes of a port (the
  `PORT_PROTOCOLS` map, `config.DEFAULT_BINDINGS`, the `Container` accessor, `settings.yaml` and
  the canonical-call table), so a port cannot be added in four places and run unenforced.
- `tests/contract/test_behavioral_parity.py` proves the offline family ANSWERS, the on-premises
  family RAISES and the managed family REFUSES rather than silently succeeding. On the extraction
  seam that refusal is the current production behaviour, not just the test's expectation.
- `make portability` is the executable claim: named checks with a pass or fail each, exiting
  non-zero on any failure. The stronger SDK-free proof lives in
  `tests/contract/_sdk_free_probe.py`, which BLOCKS the `google` import in a fresh interpreter
  rather than hoping the machine has none installed.

### Is the register format portable?

Yes, and deliberately so. The feed is not a bespoke serialiser: it is the shared kernel's envelope
over a register snapshot,
`obligation_register.schema.envelope("contract_obligation_register", register.snapshot)`, with
canonical byte-identical serialisation (sorted keys, ISO dates). The shape and its version are
frozen and held by a contract test, and the reasoning is written down in
[`../rgc8-feed.md`](../rgc8-feed.md). A consumer that reads the envelope reads it the same way
whoever is hosting this service.

### How do we actually exit?

[`../onprem-migration.md`](../onprem-migration.md) is the path. The short version: the domain is
pure stdlib and moves unchanged; the audit trail exports to and restores from JSON Lines; the
registers themselves serialise through the kernel envelope; what you implement is one adapter per
port under `adapters/onprem/`, each of which currently raises with a message naming what to bind.
Nothing in `domain/` has to change.

### Can it run with no model at all?

The register can, and does in the gate: the offline profile replays canned proposals, and every
admissibility decision, date and severity comes from code, so the consequential fields are
identical with no model reachable. What a real deployment cannot do without a model is READ a new
contract, because that is what `ExtractionPort` is for. The honest summary: the DECISIONS are
model-free, the READING is not.

### Is the data residency claim portable too?

The region is chosen once and shared by the runtime and Terraform:
`config/settings.yaml:region`, `infra/terraform/render.tf.json:render_region`, and the Terraform
`region` / `allowed_regions` pair, which refuses an unapproved region at plan time. Changing
jurisdiction is a configuration change in those three places plus a re-run of
`infra/terraform/production_edge.tftest.hcl`. The location this stack cannot pin is the document
source, which lives wherever the adopter keeps its contracts.
