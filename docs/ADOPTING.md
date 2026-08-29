# Adopting this repo as your base

This repository (Rgc12, Contract Obligation Extraction) is a **common base** that a bank or other
regulated institution forks to build its own **contract-to-register service**: read an executed or
draft contract, segment it into clauses with stable anchors, extract the obligations, key dates
and risk flags, decide which of the model's proposals are admissible, compute the renewal and
deadline clocks, and publish a tracked register that a vendor-risk system can consume. It ships a
reusable hexagonal core (a pure-stdlib domain, typed ports, three swappable adapter profiles, a
green offline gate) plus a fully worked extraction vertical you can keep, retune, or replace.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and topology),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (adding an adapter, adding a port), the
> [`faq/`](faq/) directory, [`model-card.md`](model-card.md) (the two model seams),
> [`rgc8-feed.md`](rgc8-feed.md) (the register feed's frozen wire shape),
> [`practices-audit.md`](practices-audit.md) (the per-check verdict).

---

## 1. What you keep vs what you rewrite

The core is hexagonal, and the boundary between reusable machinery and the contract vertical is a
physical module split with an enforced dependency direction (practices-audit check A7).
`domain/kernel.py` owns the vertical-neutral contracts; `domain/models.py` holds this vertical's
artifacts.

| Layer | Where | For your contract estate |
|---|---|---|
| **Vertical-neutral machinery** | `domain/kernel.py` (`Citation`, `AuditEvent`, `Severity`, `Decision`), every Protocol in `ports/`, the container wiring in `config.py` | keep untouched |
| **Register and deadline kernel** | the shared `obligation-register-kit`: the register snapshot, the canonical byte-identical serialisation (`obligation_register.schema.envelope`) and the deadline primitives (`obligation_register.deadlines`) | keep untouched, and take upstream releases |
| **The anchoring guarantee** | `domain/clauses.py`: deterministic clause segmentation with stable anchor ids, which is what makes "this obligation came from clause 7.2" trustworthy | keep untouched |
| **Policy (your taxonomy and bands)** | `domain/flags.py`: the `RiskFlag` vocabulary and the `FlagTaxonomy` policy dataclass (severities, admissibility), with `DEFAULT_TAXONOMY` as the shipped reference. Plus the jurisdiction list in `domain/pii.py` and the thresholds in `eval/run_eval.py` | change deliberately (see section 4) |
| **Vertical (the content and the flow)** | `domain/contracts.py`, `domain/renewals.py`, `domain/narration.py`, the fictional corpus in `domain/corpus.py`, the fixtures and the eval golden set | rewrite and reseed for your contract families |

If your product is another *document in, tracked register out* engine, the hexagon, the three
profiles, the propose-then-admit pattern, the eval gate and the Hrz7 review routing transfer
directly; you replace the flag taxonomy and the corpus.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): `domain/kernel.py`, `domain/clauses.py`, `ports/`,
  `tests/contract/`, the eval harness mechanics (`eval/run_eval.py`), the CI workflows, the
  hexagon wiring (`config.py` `Container`), the deploy stack in `infra/terraform/`, and the feed
  envelope described in [`rgc8-feed.md`](rgc8-feed.md).
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values*, the flag taxonomy,
  the corpus and every fixture, the golden eval dataset, `adapters/onprem/*`, UI theming and
  branding, `infra/terraform/terraform.tfvars`, and the regulator crosswalk section of
  `COMPLIANCE.md`.

Track upstream via git tags; rebase your adopter-owned changes onto each release rather than
merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name (`contract_obligation_extraction`, which is
also the console script), the `CONTRACT_` env prefix (including the bare token that
`infra/terraform/render.tf.json` carries so Terraform sets the same variable names on the
service), the cloud resource stem (`rgc12-svc`, the Terraform `name_prefix`) and the distribution
/ git id in one pass. Preview first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_contract_intel --env-prefix ACME \
    --resource acme-contracts --dry-run

# Apply:
python scripts/rename_fork.py --package acme_contract_intel --env-prefix ACME \
    --resource acme-contracts --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
```

`--dist` defaults to the `--resource` value; pass it explicitly when your git id differs from your
resource stem. `--resource` is validated against the same regex the Terraform `name_prefix`
variable enforces, so a stem the stack would refuse fails here instead of at plan time. Add
`--include-docs` to sweep Markdown prose too. The catalog id `Rgc12` is left alone unless you pass
`--catalog-id`, so a fork stays traceable to the entry it descends from. The script deliberately
does NOT touch the human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region / residency.** The build defaults to `asia-southeast1` (MAS / Singapore), chosen once
   and shared: `config/settings.yaml:region`, `infra/terraform/render.tf.json:render_region` and
   the Terraform `region` / `allowed_regions` pair. Set all of them to your in-country region and
   re-run `infra/terraform/production_edge.tftest.hcl`, which refuses a region outside the
   allowlist at plan time. Contracts are among the most residency-sensitive documents a bank
   holds, so also decide where the SOURCE documents live before you wire the extraction seam.
2. **Identity / IdP.** This repo owns no login flow: the `gcp` profile verifies the IAP-injected
   assertion at the edge, `local` uses seeded dev personas, and `onprem` is a client IdP
   placeholder. Wire your issuer on the deployed service and set `CONTRACT_IAP_AUDIENCE`. An unset
   or emptied audience refuses every caller rather than verifying without one.
3. **The risk-flag taxonomy, which is the policy.** `domain/flags.py` holds the closed `RiskFlag`
   vocabulary and the `FlagTaxonomy` that decides how severe each flag is and whether an ambiguous
   proposal is admitted or held for review. Adding a member widens what the engine will admit, so
   it is a deliberate policy edit rather than a model capability. Keep the two rules the engine
   encodes: a proposed flag outside the taxonomy is DROPPED, never coerced to the nearest known
   one, and a proposal the model marked ambiguous is ROUTED to a human, never defaulted to present
   or absent.
4. **Where the taxonomy lives.** Today it is a frozen dataclass the engine takes as an argument,
   with `DEFAULT_TAXONOMY` as the reference. There is not yet a `policy:` block in
   `config/settings.yaml` and a `from_policy(...)` that threads yours in, so setting your own
   severities is a code change. That is the open B4 item; plan the small addition if your legal or
   procurement function must own those bands as configuration.
5. **The document source and the extraction seam.** `ExtractionPort` is the Document AI plus
   long-context boundary, and its managed adapter is a declared seam that RAISES rather than a
   working client: the processor id, the layout configuration and the model are per-deployment.
   Wiring it, and deciding what a document is allowed to contain before it reaches a model, is
   yours. See [`model-card.md`](model-card.md).
6. **The corpus is fictional.** `domain/corpus.py` ships five obviously fictional contracts (MSA,
   SOW, DPA, outsourcing, ISDA) plus the canned extractor proposals the offline profile replays.
   Replace them with your own synthetic set. **Do not run against real executed contracts without
   your own legal, security and model-risk sign-off.**
7. **Eval golden set.** Rebuild the golden dataset for your contract families: a fork inherits a
   green gate that measures the WRONG documents until you do. The six metrics
   (`decision_accuracy`, `pii_safety`, `extraction_accuracy`, `flag_accuracy`,
   `deadline_accuracy`, `narration_groundedness`) and their thresholds are generic; the golden
   cases are yours.
8. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001),
   `infra/terraform/` (Org Policy, CMEK, a dry-run-first VPC-SC perimeter, the locked WORM log
   bucket) and the loopback-by-default binding before you expose anything. The WORM lock is
   irreversible: confirm `retention_days` before the first apply.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems (see
[`faq/features-faq.md`](faq/features-faq.md) for the full map):

- **Rgc8** third-party risk and DDQ consumes this register for the contractual terms behind a
  vendor's inherent and residual risk rating. The wire shape is FROZEN as a recorded proposal in
  [`rgc8-feed.md`](rgc8-feed.md), built from the shared kernel's envelope rather than a bespoke
  serialiser, and `tests/unit/test_contracts.py::test_the_rgc8_feed_carries_a_schema_version`
  holds the shape and its version stable so a later change is deliberate and reviewed.
- **Rgc7** obligations and control mapping owns the firm-wide obligation graph. A contract
  register is a source that can feed it; it is not a second copy of it.
- **Hrz7** human-review / maker-checker console: every `requires_human_review` result, including
  every ambiguous flag proposal, is routed to it over the shared `review-kit` (rule R8); you
  wire your endpoint (`HUMAN_REVIEW_URL`), you do not re-implement the console.
- **Hrz5** observability plus immutable WORM audit: audit events and trace spans go to it.
- **Hrz4** AI-quality / model-risk gate: owns promotion. `eval/run_eval.py --mode gate` is the
  client half and refuses to run off the managed profile.
- **Hrz3** agent registry: this agent publishes its A2A card at
  `/.well-known/agent-card.json`; register it rather than inventing a discovery mechanism.

The guardrail gateway (Hrz1) is **not** integrated, and it matters more here than in most repos:
a contract is untrusted third-party text that reaches a model on the extraction path. Rule R1 in
[`../COMPLIANCE.md`](../COMPLIANCE.md) records that.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` green.
- [ ] Set the region in all three places (settings, `render.tf.json`, tfvars), decided where the
      source documents live, and re-ran the Terraform residency tests.
- [ ] Wired your IdP audience on the deployed service (this repo owns no login flow).
- [ ] Replaced the risk-flag taxonomy with yours, keeping the drop-unknown and
      route-ambiguous rules.
- [ ] Decided whether the taxonomy needs to be configuration (the open B4 item) before go-live.
- [ ] Wired `ExtractionPort` to your document pipeline, with Hrz1 screening in front of it.
- [ ] Replaced the fictional corpus and every fixture.
- [ ] Rebuilt the eval golden set for your contract families.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, `retention_days`, bind address).
- [ ] Wired your Hrz7 review endpoint and agreed the Rgc8 feed version with its consumer.
- [ ] Read [`model-card.md`](model-card.md) and closed its remaining controls before enabling
      either managed model path.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
