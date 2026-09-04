# Contract Obligation Extraction (`contract-obligation-extraction`)

Structured register of obligations, key clauses, dates and risk flags extracted from contracts.

A hexagonal ports-and-adapters build scaffolded from the catalog commons. The consequential
decision is pure, deterministic stdlib; PII is redacted before anything is audited; every result
carries a citation; and a consequential result is ROUTED to a human reviewer (rule R8) rather than
auto-executed or left in a flag nobody reads.

## Commands

```bash
python3.12 -m venv .venv && source .venv/bin/activate
make install          # locked install from requirements-dev.lock, then the project --no-deps
make gate             # the full offline gate: lint + type + test + eval
make audit            # pip-audit over both lockfiles (needs network; a HARD gate in CI)
make lock             # recompile both lockfiles after a dependency change
make test-integration # tests/integration only; needs a live project (the gate deselects it)
make run-api          # uvicorn (loopback for the no-auth local profile)
contract_obligation_extraction triage "Acme (FICTIONAL)" "urgent data breach"
contract_obligation_extraction register apex-outsourcing-2026   # read a corpus contract
```

## The vertical

`contract-obligation-extraction` reads an executed or draft contract (MSA, SOW, DPA, outsourcing agreement, ISDA) into a
tracked, owner-assigned, deadline-bearing register of obligations, key clauses, dates and risk
flags, each linked to its source clause. The model PROPOSES; the deterministic engine OWNS the
result: clause segmentation gives every clause a stable anchor and a candidate citing an unreal
clause is dropped; the config-owned risk-flag taxonomy validates every proposed flag and drops the
unknown ones; the renewal clock computes what is breached or inside its notice window; the severity
band is pure code; and a material register routes to a human reviewer. The obligation model,
admission and versioning come from `obligation-register-kit`, pinned by the SAME tag `obligations-control-mapping` pins, so
one engine serves the regulatory and the contractual corpora. `POST /v1/register`, the `register`
CLI command and the `extract_contract_register` agent tool run one flow, and the response carries
the versioned feed the `third-party-risk-ddq` vendor-risk system consumes (see `docs/rgc8-feed.md`). Seed contracts
in the corpus are obviously fictional and stand in for uploaded documents offline.

The offline gate is SDK-free and is what CI runs (via the shared reusable hard-gate workflow):

```bash
ruff check src tests && ruff format --check src tests && mypy src && \
  pytest -m 'not integration' && python eval/run_eval.py
```

The demo surface sits OUTSIDE that gate, because the gate proves the service and the demo proves
the story it is presented with. It is enforced inside the offline gate by
`tests/unit/test_demo_surface.py`, which the hosted GitHub Actions check runs, so it cannot rot
quietly:

```bash
make demo             # the presenter-paced walkthrough (see DEMO.md)
make demo-selftest    # the same walkthrough, headless and unattended, asserting every step
make demo-static      # static audit-first HTML for screenshots
make portability      # the executable portability claim, pass or fail per named check
make docs-check       # relative links resolve, fences close, no em-dash in shipped prose
make ui-install ui-check   # the micro-frontend: tsc, node tests, production build, npm audit
```

## Profiles

One env var, `CONTRACT_PROFILE`, selects the adapter family:

- `local` (default) : SDK-free offline stack (seeded dev personas, hash-chained SQLite WORM audit
  from the commons). No cloud SDK. The default for dev/test/CI.
- `gcp` : managed cloud (Cloud Logging WORM, IAP identity). SDK imports are lazy.
- `onprem` : fail-fast `NotImplementedError` placeholders (the reversibility proof, P-12).

Unset means `local` adapters bind but nobody chose them. A value that is set but unknown, `Local`
and `GCP` included, raises at import: a typo must not silently pick a family. And because the
local profile's seeded personas authenticate nobody, the loopback exposure guard is registered on
the app object itself, so serving it off loopback returns 503 unless
`CONTRACT_ALLOW_INSECURE_DEMO=1` says otherwise. The guard reads the identity
BINDING to decide that, never a service credential: setting
`CONTRACT_S2S_TOKEN` closes the S2S routes and does not open anything else.
See `docs/runbook.md`.

## What comes from the commons

| Package | Used for |
|---|---|
| `hex-service-kit` | `Principal` / `IdentityPort` / seeded personas, fail-closed bind + CORS, `make_require_service_caller` / the app-object exposure guard / security headers (the end-user dependency is this repo's own, so a deployment that can authenticate nobody answers with a status and a reason rather than a blanket 401), the hash-chained WORM audit log, `StrEnum` taxonomies |
| `agent-eval-kit` | the `--mode smoke\|gate` scaffold, the `model-quality-gate` client, the not-falsely-green harness |
| `pii-kit` | the jurisdiction PII pattern pack the triage service redacts with |
| `review-kit` | the rule R8 producer path: the review payload, the submission client and the outbox |

## Surfaces

The same capability is reachable five ways, and they behave the same because they share the
domain service rather than reimplementing it: the FastAPI app (`api/`), the argparse CLI
(`cli/`), the agent tools (`agent/`, advertised on the A2A card at
`/.well-known/agent-card.json`), the embeddable micro-frontend (`ui/`) and the eval harness.
Each of them routes an escalated result to human review in the same call that produced it, so
rule R8 does not hold on four surfaces out of five.

`ui/` is a Next.js micro-frontend that runs standalone or embeds in a client application. Its
security value is that the browser never asserts who the user is: every client-supplied actor,
tenant, role and authorization header is discarded, identity is resolved server-side, the
service credential never leaves the server, and framing and CORS are per-tenant allowlists that
refuse a wildcard. **If this repo has no user-facing surface, run `make drop-ui`** rather than
leaving it half-wired; `tests/unit/test_ui_surface.py` holds the repo consistent in both
directions. See `ui/README.md`.

The tool results are masked for personal data before they return, which the API response is not:
a tool result becomes a model's context, and P-04 is about what reaches the model.

## Configuration

`config/settings.yaml` holds the per-port adapter map plus non-secret defaults, and it is the only
place a binding lives. `.env.example` documents every non-secret variable;
`.env.secrets.example` documents the secret NAMES with placeholder values. Every security-relevant
read resolves three states: unset, set-and-empty and set-and-valid are different, and a value an
operator deliberately emptied never inherits the more permissive unset default.
`tests/unit/test_three_state_env_reads.py` fails the build on any two-state read that ships, so
the rule is enforced rather than remembered.

**Name the profile.** `CONTRACT_PROFILE` has no default. Leaving it unset is
its own state: the offline adapters still bind, but the seeded dev personas are refused, no
service-to-service scheme is selected, the dev CORS allowlist and the `X-Dev-Persona` header are
withdrawn, and the exposure guard refuses every route to any non-loopback peer. A deployment that
loses the variable fails visibly instead of serving a stranger.

Deepest authority on intent, in order: `SPEC.md` -> `ARCHITECTURE.md` -> `COMPLIANCE.md` -> this
file. `docs/practices-audit.md` records the per-check verdict. Region pinned to
`asia-southeast1`.

## License

Apache-2.0. Synthetic, obviously fictional data only.
