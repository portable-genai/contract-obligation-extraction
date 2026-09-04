# SPEC: Contract Obligation Extraction (`contract-obligation-extraction`)

Locked decisions, pinned stack, contracts. This document is the deepest authority on intent.

## Pinned stack
- Python `>=3.12`; ruff pinned exactly (`0.15.18`); mypy strict; deploy region `asia-southeast1`.
- Commons declared by tag in `pyproject.toml` (`pii-kit@v0.0.1`, `hex-service-kit@v0.0.1`, `agent-eval-kit@v0.0.1`, `review-kit@v0.0.1`) and pinned in the lockfiles to the 40-character COMMIT each tag resolved to. A tag can be moved; a commit cannot, so a lockfile that pinned the tag would let what installs change with no diff. `tests/unit/test_repo_artifacts.py` asserts the three-way agreement offline.
- The `hex-service-kit` pin is a security floor, not a preference: the kit checks the
  service-identity policy before the token, gates the zero-secret local opening on an exact
  profile match, and binds the loopback exposure guard over both HTTP and WebSocket scopes; it
  resolves every environment read in three states, so a variable set to empty fails closed
  instead of inheriting the unset default. Never move this pin backwards.
- Installs are LOCKED: `requirements-dev.lock` and `requirements-gcp.lock` are committed and are
  what `make install`, CI and the container image install. Nothing ships from an uncommitted
  resolve.

## Contracts
- **Identity**: a request's actor is a server-verified `Principal`; the client-supplied actor is
  discarded. Local profile resolves a seeded dev persona from `X-Dev-Persona`.
- **Redaction before audit**: the triage service redacts PII (via `pii-kit`) before writing any
  audit record. No raw identifier reaches the WORM store.
- **Determinism**: the severity band and escalation decision are pure stdlib and replayable; an
  LLM may narrate but never produces the band.
- **Maker-checker (P-06) and routing (R8)**: a HIGH/CRITICAL result sets
  `requires_human_review=True` AND is routed through `ReviewRouterPort` to the `human-review-console` in the
  same request. The flag alone is not the escalation. The response carries `review_ref`, so a
  caller can tell a routed escalation from one that stopped here. The managed adapter refuses to
  run with no console configured rather than swallowing the escalation.
- **Profile**: resolved ONCE, at import, into a `ProfileChoice` and never a bare string. Three
  states of `CONTRACT_PROFILE`: UNSET is NO CHOICE (the SDK-free adapters
  still bind, but the seeded personas are refused, no service-to-service scheme is selected, every
  relaxation sees `unconfigured` and the exposure guard refuses every route to a non-loopback
  peer); SET AND EMPTY raises, so it can never inherit the unset behaviour; SET AND UNKNOWN,
  including a mis-capitalised value, raises. Only a deliberately named profile is honoured, and
  both raises happen before the process can serve anything.
- **Two derived postures, opposite directions**: `exposure_profile` drives every RELAXATION (CORS
  allowlist, the `X-Dev-Persona` allowed header, the HSTS baseline, the S2S scheme) and reads
  `unconfigured` when nobody chose; `bind_profile` drives the RESTRICTION (the loopback bound) and
  reads `local` when nobody chose. One string cannot do both without weakening one of them.
  Only `config.py` reads the variable.
- **End-user authentication is a property of the identity BINDING**, declared by the adapter
  (`VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`) and read by the loopback exposure guard. The
  service-to-service secret authenticates a calling SERVICE and no end user, so it takes no part
  in that decision: setting it closes the S2S routes and relaxes nothing.
- **Audit integrity**: the trail is hash-chained AND externally anchored. `audit_anchor_path`
  points at a file on a different volume that every append writes the chain head to; without it
  a truncated tail is undetectable, because the shorter chain still verifies. Once store and
  anchor disagree the service refuses to append rather than re-anchoring, so an ordinary write
  cannot launder a divergence. Re-anchoring is a deliberate operator action.
- **Agent surface**: optional but scaffolded. The A2A card at `/.well-known/agent-card.json` is
  built from the same tool table the runtime binds, so advertised skills and implemented tools
  are the same set. Tool results are masked for personal data before they return, because a tool
  result becomes model context (P-04); an API response to the caller who supplied the text is
  not. Nothing in `agent/` needs a runtime to import; `build_function_tools()` is the only seam.
- **Ports**: a port is registered in five places (`PORT_PROTOCOLS`, `DEFAULT_BINDINGS`, the
  `Container` accessor, `config/settings.yaml`, and the canonical-call table) and the contract
  suite asserts set equality across all five, in both directions.
- **Demo**: the demo is code and it is asserted. `scripts/walkthrough.py` narrates nine steps
  (one of them the contract register itself) and, at each one, checks that the service actually
  reached the state the narration claimed;
  `--auto --headless` runs the same steps unattended in CI. A step exists in exactly two places
  (`demo.STEPS` and `walkthrough.CHECKS`) and the two are held equal, so a narrated claim nobody
  verifies cannot exist. The demo needs no browser engine, no network and no cloud.
- **UI identity**: the browser never asserts who it is. Every client-supplied actor, tenant,
  role, ACL and authorization header is discarded before a request is forwarded; identity is
  resolved server-side and the resolved headers are attached afterwards. The service credential
  is read from the server environment only. Framing and CORS are allowlists that refuse a
  wildcard however it is written, and an empty allowlist denies rather than opening up.
- **Eval**: `--mode smoke` is the offline pre-merge check; `--mode gate` is the `model-quality-gate` promotion
  authority. The gate fails closed.
- **Tests**: split into `unit`, `contract` and `integration`. The offline gate runs the first
  two; every integration module is marked, and that marking is itself enforced.

## Vertical: the contract obligation register
`contract-obligation-extraction` reads an executed or draft contract (MSA, SOW, DPA, outsourcing agreement, ISDA) into a
tracked, owner-assigned, deadline-bearing register of obligations, key clauses, dates and risk
flags, each linked to its source clause. The consequential computation is pure code; the model
only proposes and narrates.

- **Shared engine, contractual corpus**: the obligation model, admission (dedup on a content key),
  versioned effective-dated snapshots and the coverage/deadline primitives come from
  `obligation-register-kit`, pinned by the SAME tag that `obligations-control-mapping` pins. This repo applies the kernel's
  admission rules to a contractual corpus rather than a regulatory one; it never vendors the
  kernel.
- **Clause segmentation is the linkage**: `domain/clauses.py` splits a contract at numbered-heading
  boundaries and derives each clause's anchor from its NUMBER, not its parse position, so a stable
  anchor survives an inserted recital. Admission refuses any extracted candidate whose cited anchor
  is not one the segmentation produced: an uncited or fabricated linkage is dropped, never
  defaulted to a nearest clause.
- **The extraction port** (`ports/extraction.py`) is where the model reads: a Document AI plus
  long-context adapter under `gcp` (lazy imports), a deterministic fixture reader under `local`,
  fail-fast under `onprem`. It PROPOSES obligations, dates and flags; it decides nothing.
- **Risk-flag taxonomy is config-owned** (`domain/flags.py`, practices check B4): the seven
  families (termination/renewal, liability cap, indemnity, audit/step-in, sub-outsourcing, data
  residency, SLA commitment) are a frozen policy object with a severity per family and an
  always-review mark on step-in and sub-outsourcing. A proposed flag outside the taxonomy is
  dropped and the row is held for review as an unresolved classification; an ambiguity the model
  signals lands in needs-review, never a default flag.
- **The renewal clock** (`domain/renewals.py`) is pure date maths with an explicit `as_of`: a
  renewal or termination right is actioned a NOTICE PERIOD before its due date, so an obligation
  can be inside its action window before it is "due soon"; a past due date is a breach. A breached
  deadline is consequential and routes to `human-review-console`.
- **Severity and escalation are pure code**: the band is the worst admitted flag severity, lifted
  to HIGH on any breach; a register carrying any material finding sets `requires_human_review` and
  routes to `human-review-console` (R8). The model narrates the register summary and the note is discarded unless it
  validates and every figure in it is one the engine produced.
- **The `third-party-risk-ddq` feed** is versioned from day one: `register_envelope` wraps the register snapshot in
  the kernel's schema envelope (`schema_version`, `kind`, `payload`). `third-party-risk-ddq` consumes it;
  until it exists the shape is a recorded PROPOSAL frozen by a contract test, not an agreement. See
  `docs/rgc8-feed.md`.
- **Cross-tenant**: a contract is tenant-owned; the read is authorised against the VERIFIED
  principal's tenant and a caller from another tenant is refused with 403, never 404.
- **Surfaces**: `POST /v1/register` (REST), a `register` CLI command and the
  `extract_contract_register` A2A tool all run one flow (`flow.py`) so R8 routing is on every path.

## Metrics and thresholds (smoke)
- `decision_accuracy >= 0.80` (the generic triage example vertical, retained)
- `pii_safety >= 0.99` (pack scan + pack-independent planted-literal check)
- `extraction_accuracy >= 0.99` (admitted clause linkages and dropped count vs an independent oracle)
- `flag_accuracy >= 0.99` (validated risk flags per obligation vs the golden labels)
- `deadline_accuracy >= 0.99` (breach / notice-window / due status vs a hand-computed calendar)
- `narration_groundedness >= 0.99` (every figure in the register summary comes from the engine)

Each contract metric is proved able to go red: `assert_each_can_go_red` falsifies flag
classification per family and clause linkage per contract family in
`tests/unit/test_extraction_falsification.py`.
