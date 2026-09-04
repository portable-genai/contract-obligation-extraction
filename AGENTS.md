# contract-obligation-extraction

The shared working agreement is [`.github/AGENTS.md`](https://github.com/portable-genai/.github/blob/main/AGENTS.md).
It carries the architecture rules, the gate contract, the fleet invariants, the
falsification discipline, versions and house style, and it holds in every repository
here. Read it first. This file carries only what is specific to this one.

## What this is

Contract Obligation Extraction (`contract-obligation-extraction`): Structured register of obligations, key clauses, dates and risk flags extracted from contracts.
Rendered from `hex-service-template`, so it starts at reference parity rather than converging
toward it. Package `contract_obligation_extraction`, environment prefix
`CONTRACT`, region `asia-southeast1`.

## Repository documents

`docs/runbook.md` and `docs/onprem-migration.md` are operational and never restate product
behaviour. `docs/practices-audit.md` records the per-check verdict against the common base
practices, and it is the file to update when a gap closes.

## The hard gate

```sh
make install   # locked install from requirements-dev.lock, then the project with --no-deps
make gate      # ruff check + ruff format --check + mypy src + pytest -m 'not integration' + eval
make audit     # pip-audit over both lockfiles (needs network; CI runs the same two commands)
```

`make audit` is the one step that needs a vulnerability feed, which is why it is separate
locally and a hard-failing job in CI rather than an advisory one.

After any dependency change, run `make lock` and commit both lockfiles. An uncommitted resolution
is a version set nobody reviewed.

## Architecture

Hexagonal, ports and adapters:

- `src/contract_obligation_extraction/domain/` is PURE stdlib. No web framework, no cloud SDK,
  no HTTP. `kernel.py` holds the vertical-neutral machinery; `models.py` holds this vertical's
  artifacts. A fork building a different vertical rewrites `models.py` and leaves `kernel.py`.
- `ports/` holds `@runtime_checkable` Protocols, re-exported once from `ports/__init__.py` with
  the `PORT_PROTOCOLS` map, plus `ports/identity.py`: what an identity adapter declares about the
  end-user authentication it provides, and the refusal type that carries a status and a reason.
- `adapters/{local,gcp,onprem}/` are the three families. `local` is SDK-free and actually works;
  `gcp` imports its SDK LAZILY inside the method, so the other two profiles import it with no
  cloud SDK installed; `onprem` is a placeholder that RAISES rather than pretending.
- `config.py` resolves the profile and binds every port. `config/settings.yaml` carries the
  binding table, so switching a port is configuration, not a code edit.
- `agent/` is the optional-but-scaffolded agent surface: plain tool callables plus the A2A card.
  It imports with no ADK and no cloud SDK; `build_function_tools()` is the only runtime seam.
- `tests/` splits into `unit/`, `contract/`, `integration/` and `fixtures/`. Integration modules
  are marked so `pytest -m 'not integration'` deselects them, and a test dropped into `tests/`
  root fails `tests/unit/test_test_layout.py`.
- `scripts/` is the demo surface (see `scripts/README.md`): the scripted arc, a static renderer,
  a live click-through server, the presenter walkthrough that doubles as the self-test, the
  executable portability claim and the offline documentation checker. It is importable from the
  suite (`pythonpath = ["scripts"]`) and excluded from the serving image.
- `ui/` is the embeddable micro-frontend. One policy module and one server-side identity module
  are its whole security boundary. Run `make drop-ui` if this repo has no user-facing surface.

## Invariants (a change that breaks one of these is a defect, not a trade-off)

- **Born fail-closed.** `add_loopback_exposure_guard` is bound at MODULE scope in `api/app.py`,
  because the Dockerfile `CMD` and `make run-api` serve the app OBJECT: a bound that lives only
  in `main()` never runs in a shipped process. `tests/unit/test_serving_path_exposure.py` is the
  standing gate.
- **The exposure guard is derived from the IDENTITY BINDING, and from nothing else.** An end-user
  route is authenticated when the bound identity adapter can produce a verified principal without
  trusting a header the client wrote, and the adapter DECLARES that (`ports/identity.py`:
  `VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`, defaulting to client-asserted when silent).
  `CONTRACT_S2S_TOKEN` may never enter that decision: it authenticates a
  calling SERVICE and no end user, and while it did, SETTING it switched the guard off for the
  end-user routes it was protecting and a LAN peer with no credential got the seeded approver
  persona and a real triage decision. `tests/unit/test_end_user_auth_posture.py` walks the
  guard's argument through the constants it names and fails the build if a credential reappears
  at any depth; `scripts/prove-exposure-matrix.sh` in the template drives the whole matrix over a
  real socket.
- **The one adapter that declares `VERIFIED` must EARN it, and it is the one adapter that may not
  go untested.** `adapters/gcp/identity.py` calls `id_token.verify_token` with `audience=` (the
  configured `CONTRACT_IAP_AUDIENCE`, three-state: unset or emptied REFUSES,
  because `audience=None` means the audience is NOT verified and accepts any Google-signed token
  from any project) and `certs_url=` (IAP's own key set, not google-auth's OAuth2 default), checks
  the issuer itself (`verify_token` does not), and WRAPS both the verifier call and the lazy
  import so no caller-supplied header can become a 500. `MalformedError` is a `ValueError`, not an
  `IdentityError`. Caller faults are 401 with the reason kept in the log; deployment faults (no
  audience, no verifier installed) are 503 naming the fix. `tests/unit/test_iap_identity.py` runs
  in every `make gate`; `tests/unit/test_iap_crypto_matrix.py` runs the REAL verifier over
  locally minted assertions and is required by the `iap-verifier` CI job and by the template's
  render gate, which fail if it skips. There is no `# pragma: no cover` on this adapter.
- **Interactive docs are a relaxation, not a constant.** `/docs`, `/redoc` and `/openapi.json` are
  registered only when `exposure_profile` is the deliberate `local`. Under `gcp` the loopback
  guard has stood down and the process binds every interface, so an uncredentialed peer was
  receiving the whole route inventory and every schema; the routes are ABSENT there rather than
  guarded, because a guard the profile has switched off is no guard.
- **One profile read, three states, refused at import.** `config.PROFILE_CHOICE` resolves once at
  import into a `ProfileChoice`. UNSET is NO CHOICE, not a silent `local`; SET-AND-EMPTY raises so
  it cannot inherit the unset behaviour; SET-AND-UNKNOWN raises. Both raises kill the process
  before it can serve a request. Only `config.py` may read
  `CONTRACT_PROFILE` (mentioning it in a refusal message is wanted, reading
  it is the defect); `tests/unit/test_profile_single_source.py` fails the build if any other
  module re-derives it, because a permissive default gets reintroduced one module at a time.
- **Two derived postures, never one string.** Relaxations (CORS, the `X-Dev-Persona` allowed
  header, HSTS, the S2S scheme) key off `ProfileChoice.exposure_profile`, which is `unconfigured`
  when nobody chose. The loopback bound keys off `ProfileChoice.bind_profile`, which is `local`
  when nobody chose. They fail closed in OPPOSITE directions, so a single effective-profile
  string would harden one and weaken the other. The seeded-persona adapter refuses to construct
  unless `local` was chosen deliberately.
- **The audit trail is anchored, not just chained.** `audit_anchor_path` writes the chain head to
  a file on another volume. The chain catches an edit, a deletion or a reorder; only the anchor
  catches a truncated tail. `tests/unit/test_audit_anchor.py` proves both, including the control
  case that fails without it.
- **Three-state environment reads, everywhere, enforced, in BOTH languages.** UNSET,
  SET-AND-EMPTY and SET-AND-VALID are three states, not two. A variable an operator deliberately
  emptied must never inherit the unset default. In Python use
  `hex_service_kit.netdefaults.read_env_setting`; `tests/unit/test_three_state_env_reads.py`
  walks the AST of `src/`, `scripts/` and `eval/` and fails the build on any two-state
  `os.environ.get` / `os.getenv` read that is neither an exact-match comparison against a literal
  nor listed with a written reason. In `ui/` use `readEnvSetting` from `ui/lib/env-setting.mjs`;
  `ui/tests/three-state-env-reads.test.mjs` scans every shipped `.mjs` / `.ts` / `.tsx` with the
  same rule and the same two escapes. Both halves are needed: a guard that only watched the
  PROFILE variable is how a two-state read of a different one stayed invisible, and a guard that
  only parsed Python is how `env.UI_TENANT_ORIGINS || "*"` survived the entire gate.
- **Rule R8: escalations are ROUTED, never merely flagged.** Setting `requires_human_review` and
  calling `ReviewRouterPort.route` is one act. `api/app.py`, `cli/main.py` and `agent/tools.py`
  all route in the same call that produced the result. `tests/unit/test_review_routing.py` is the
  standing gate; a local router that silently did nothing would let a producer ship R8 unwired
  and green.
- **The consequential decision is deterministic.** The severity band and the escalation come from
  pure stdlib code and are replayable. An LLM may narrate the result; it may never produce the
  band.
- **The demo is code, and every narrated claim is checked.** A step lives in `demo.STEPS` and in
  `walkthrough.CHECKS`, and `tests/unit/test_demo_surface.py` holds the two equal, so a claim the
  demo makes but nobody verifies cannot exist. `make demo-selftest` runs the whole arc headless
  in CI. Do NOT move the demo into `make gate`: the gate proves the service and must stay fast
  and offline, and the demo has its own required check.
- **The browser never asserts who it is.** In `ui/`, every client-supplied actor, tenant, role,
  ACL and authorization header is discarded before forwarding, identity is resolved server-side,
  and the service credential stays on the server. Framing and CORS are allowlists that refuse a
  wildcard, and every variable behind them is read in three states: unset takes the documented
  restrictive default, EMPTIED refuses. `UI_PROFILE` refuses rather than seeding a dev persona
  when nobody chose; `UI_FRAME_ANCESTORS` and `UI_TENANT_ORIGINS` refuse from `next.config.mjs`,
  so the refusal is a build/boot refusal rather than a surprise on a later request. The one
  deliberate exception is the OUTBOUND `AGENT_S2S_TOKEN`, exempted with a written reason because
  the receiver decides whether an uncredentialed call is acceptable.
- **`ui/`, its dependabot ecosystem and its CI job agree, in both directions.** Present together
  or absent together. `make drop-ui` is the one step that keeps them consistent, and
  `tests/unit/test_ui_surface.py` fails the gate until they do.

## Extending

`CONTRIBUTING.md` carries the file-by-file touch list for both walkthroughs, with the test that
enforces each row. The short version:

- **A new adapter:** the class under `adapters/<family>/` (one constructor shape,
  `Adapter(settings)`, cloud imports inside the method), the same `module:Class` target in
  `config.DEFAULT_BINDINGS` AND `config/settings.yaml` (`tests/unit/test_settings_file.py` fails
  if the two disagree), plus any new variable in `.env.example`.
- **A new port:** it must be registered in FIVE places, or it runs with no enforcement at all:
  `ports/__init__.py` (`PORT_PROTOCOLS`), `config.DEFAULT_BINDINGS`, a `Container` accessor,
  `config/settings.yaml`, and a `PortCase` in `tests/contract/canonical.py`. Then bind it in all
  three families. `tests/contract/test_port_parity.py` asserts set equality across the five.
- **A new surface:** whatever it is, it routes escalations (R8) and it minimises what it hands a
  model. An agent tool also needs its skill in `agent/agent_card.py`; the card and the tool table
  are compared for set equality.
- **A new demo step:** the `Step` and its `_step_<key>` method in `scripts/demo.py`, plus the
  matching entry in `walkthrough.CHECKS`. Put the numbers the check reads in the step's `facts`
  dict, never only in the rendered rows: a check that parses prose breaks on a wording change.
