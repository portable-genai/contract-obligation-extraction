# Adoption FAQ

For an engineering lead forking this repo as their institution's contract-register service. The
step-by-step is [`../ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?"
questions.

### How do I rebrand it for my organisation?

`scripts/rename_fork.py` rewrites the package name (`contract_obligation_extraction`, which is
also the console script), the `CONTRACT_` env prefix (including the bare token that
`infra/terraform/render.tf.json` carries, so Terraform sets the same variable names on the
service), the Terraform `name_prefix` resource stem (`rgc12-svc`) and the distribution / git id in
one pass. Preview with `--dry-run`, apply with `--yes`, then recreate the venv, `make install`,
and run `make gate`. The catalog id `Rgc12` is left alone unless you pass `--catalog-id`, so a
fork stays traceable to the entry it descends from. The script does the mechanical rename; the
human decisions (region, IdP, the flag taxonomy, the corpus, the eval golden set) are the
checklist in `ADOPTING.md`.

### If several institutions fork this, how does each take upstream fixes?

Track upstream via **git tags**. The repo declares a core-vs-adopter-owned boundary
(`ADOPTING.md` section 2): upstream owns `domain/kernel.py`, `domain/clauses.py`, `ports/`,
`tests/contract/`, the eval harness mechanics, CI, the Terraform stack and the feed envelope; you
own `config/settings.yaml` values, the flag taxonomy, the corpus and fixtures, the golden set,
`adapters/onprem/*`, UI theming and `terraform.tfvars`. The register arithmetic is a separate
upstream package (`obligation-register-kit`) pinned by commit, so you take its fixes by bumping
the pin rather than by merging code.

### What do we have to supply that is not in this repo?

Four things:

1. **Your contracts**, replacing the five fictional ones in `domain/corpus.py`, and a document
   source to read them from.
2. **A working extraction path.** `adapters/gcp/extraction.py` is a DECLARED seam that raises: the
   Document AI processor id, the layout configuration and the long-context model are
   per-deployment. This is the biggest single piece of adoption work.
3. **Your risk-flag taxonomy**, in `domain/flags.py`.
4. **The review console.** An Hrz7 deployment reachable at `HRZ_HUMAN_REVIEW_URL`. Every ambiguous
   flag proposal goes there, so it is load-bearing here rather than an edge case, and the managed
   router REFUSES to swallow an escalation when it is empty.

### Can I retune the taxonomy without touching code?

Not yet, and the honest position is "half done". The taxonomy IS a frozen policy dataclass
(`FlagTaxonomy`) that the engine takes as an argument, with `DEFAULT_TAXONOMY` as the shipped
reference, so it is injectable rather than scattered through the engine. What does not exist is a
`policy:` block in `config/settings.yaml` and a `from_policy(...)` that threads yours in, so
setting your own severities and admissibility bands is a code change today. That is the open B4
item in [`../practices-audit.md`](../practices-audit.md), and the missing half is small.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list and a contract test that enforces it. A port must be registered in
FIVE places or it runs with no enforcement at all: `ports/__init__.py` (`PORT_PROTOCOLS`),
`config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`, and a `PortCase` in
`tests/contract/canonical.py`. Then bind it in all three families.
`tests/contract/test_port_parity.py` asserts set equality across the five. A document-store port
is the one a real deployment adds first. See [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How stable is the register feed my consumer reads?

Stable on purpose, and version-stamped. The feed is the shared kernel's envelope over a register
snapshot rather than a bespoke serialiser, and
`tests/unit/test_contracts.py::test_the_rgc8_feed_carries_a_schema_version` holds the shape and
its version so a change is deliberate and reviewed rather than accidental. The reasoning, and the
fact that it is a recorded PROPOSAL rather than an agreement (Rgc8 was not built when it was
frozen), is in [`../rgc8-feed.md`](../rgc8-feed.md). If you change it, bump the version in the
same commit.

### Why are there two verticals in here?

The render started from the template's generic triage service and the contract vertical was built
alongside it. `domain/triage_service.py` (with `/v1/triage` and the CLI `triage` command) is
scaffolding; `domain/clauses.py`, `domain/contracts.py`, `domain/flags.py`, `domain/renewals.py`
and `domain/narration.py` (with `/v1/register`) are the reason this system exists. A fork that
only wants the register can delete the triage path, its tests and its routes.

### Does the gate run for my fork out of the box?

Yes. `make gate` is offline, credential-free and network-free (ruff, ruff format, mypy strict, the
whole suite except integration, and the eval), and the CI workflow references no `secrets.`, so a
fork's build is green immediately. The offline profile replays canned extractor proposals against
the fictional corpus, so the whole arc including the extraction path runs with no model. Note the
eval measures those reference documents until you rebuild the golden set for your own contract
families.

### The eval reports high scores across six metrics. Should we believe them?

Only because each is proved able to report something else.
`tests/unit/test_not_falsely_green.py` hands the metrics planted mutants and fails the build if
they still pass. Read the metric names carefully though: with the canned proposals bound,
`extraction_accuracy` measures the pipeline's handling of a fixed proposal set, not a real
model's reading of a real contract. Measuring that is what a managed-profile eval run is for, and
it does not exist yet.

### Will the demo rot after I diverge?

It is guarded, and the guard is inside the gate. A demo step lives in `demo.STEPS` and in
`walkthrough.CHECKS`, and `tests/unit/test_demo_surface.py` holds the two equal, so a claim the
demo makes but nobody verifies cannot exist. `make demo-selftest` runs the whole arc headless over
the real loopback server and exits non-zero when a claim stops being true.

### What is still open?

[`../practices-audit.md`](../practices-audit.md) carries the per-check verdict and the work list.
The three that matter most before production: the managed extraction adapter, the Hrz1 guardrail
in front of it (a contract is untrusted third-party text), and registering this repo's metric
bundle with Hrz4 so `eval/run_eval.py --mode gate` has an authority to ask. The Terraform stack is
written, validated and tested against a mocked provider; it has never been applied.
