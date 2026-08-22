# Contributing

## The rules that are not negotiable

- **The gate must be green before anything lands:** `make gate` (ruff check, ruff format check,
  mypy strict, `pytest -m 'not integration'`, eval). CI runs the same via the shared reusable
  hard-gate workflow. The gate is OFFLINE: if a change makes it need network, credentials or a
  cloud SDK, the change is wrong, not the gate.
- **Keep `domain/` pure stdlib.** No web framework, no cloud SDK, no HTTP client. Cloud imports
  stay INSIDE the method in `adapters/gcp/*`.
- **A consequential output is ROUTED, never merely flagged** (rule R8). Setting
  `requires_human_review` and calling `ReviewRouterPort.route` is one act, on every surface.
- **Three-state environment reads.** Unset, set-and-empty and set-and-valid are three different
  states. A value an operator deliberately emptied never inherits the unset default.
- **Only `config.py` reads the profile.** `tests/unit/test_profile_single_source.py` fails the
  build if a second module re-derives it, because a permissive default comes back one module at
  a time.
- **Bump a commons package deliberately** (edit the pinned tag in `pyproject.toml`), then run
  `make lock` and commit both lockfiles. Never float a version, never ship an uncommitted resolve.
- **No em-dashes or en-dashes** in `.md` files or commit messages. Use a colon, a comma, or
  rephrase. Synthetic, obviously fictional data only: fictional parties, `.example` domains,
  RFC 5737 and RFC 3849 addresses.
- **Commits are authored solely by the maintainer.** No co-author trailers.

## Where a test goes

| Suite | What belongs there |
|---|---|
| `tests/unit/` | One module or one service. Drive the REAL `local` adapters, not bespoke fakes, so the offline implementation lives in exactly one place. |
| `tests/contract/` | Boundary claims that hold for EVERY adapter family: conformance, the drift guard, behavioural parity. |
| `tests/integration/` | Anything needing a live service. Mark the module `pytestmark = pytest.mark.integration` (enforced) and skip, never fail, when configuration is absent. |
| `tests/fixtures/` | Shared data only. No helper that makes an assertion. |

## Walkthrough: adding a DEMO step

The demo is code, and every narrated claim is checked. A step lives in exactly two places and the
offline gate holds them equal, so there is no way to narrate something nobody verifies.

| File | What to add | Enforced by |
|---|---|---|
| `scripts/demo.py` | a `Step(...)` in `STEPS` and a `_step_<key>()` method returning panels plus a `facts` dict | `_perform` looks the method up by key, so a missing one fails immediately |
| `scripts/walkthrough.py` | an entry in `CHECKS` keyed by the same string, returning the problems it found | `tests/unit/test_demo_surface.py::test_the_arc_and_its_assertions_cannot_drift` |
| `scripts/README.md` | nothing, unless you added a SCRIPT | `test_every_script_is_documented_and_every_documented_script_exists` |
| `DEMO.md` | a row in the walkthrough table, so the presenter knows the point to make | reviewed, not enforced |

Put the numbers a panel shows in `facts` as well as in the rows. The rows are for the audience;
`facts` is what the check reads, and a check that parses rendered prose is a check that breaks on
a wording change.

## Walkthrough: adding an ADAPTER (a new implementation of an existing port)

Touch these files, in this order. Every one of them is enforced by a test, so a half-wired
adapter fails the build rather than sitting inert.

| # | File | What to add | Enforced by |
|---|---|---|---|
| 1 | `src/contract_obligation_extraction/adapters/<family>/<port>.py` | The class. Exactly one constructor shape: `def __init__(self, settings: Settings)`. Cloud SDK imports go INSIDE the method that needs them. | `test_port_parity.py::test_adapter_constructs_with_a_single_settings_argument` |
| 2 | `src/contract_obligation_extraction/config.py` | The `module:Class` target in `DEFAULT_BINDINGS[<port>][<profile>]`. | `test_port_parity.py::test_every_port_binds_every_known_profile` |
| 2b | An IDENTITY adapter only | `end_user_auth = VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED` on the class (`ports/identity.py`). The exposure guard reads it to decide whether the service may be reached off loopback at all; silence is read as client-asserted, so an unannotated adapter is confined rather than trusted. | `test_end_user_auth_posture.py::test_every_bound_identity_adapter_declares_explicitly` |
| 2c | An adapter that declares `VERIFIED` | The declaration is a claim, and these are the four ways it stops being true. **Bind the AUDIENCE**, from configuration, three-state, refusing when unset or emptied: a verifier called with no expected audience accepts any token its issuer ever signed for anyone. **Pin the KEY SET** to the issuer's own, never the library's default. **Check the ISSUER yourself** unless the library documents that it does. **WRAP** the verifier call AND its lazy import, so a malformed, expired, wrong-audience or wrong-key assertion is a 401 and a missing library is a 503, never a 500 out of a route. Then write the negative matrix: mint a key locally and prove each of those is REFUSED, plus one correct assertion that is not. See `adapters/gcp/identity.py` and its two test modules. | `tests/unit/test_iap_identity.py`; `tests/unit/test_iap_crypto_matrix.py` (required by the `iap-verifier` CI job, which fails if it skips) |
| 3 | `config/settings.yaml` | The SAME target under `adapters.<port>.<profile>`. The two tables are compared for exact equality; there is no winner, only agreement. | `tests/unit/test_settings_file.py` |
| 4 | `.env.example` and `.env.secrets.example` | Any new variable, by NAME, with a non-secret default or a placeholder. Never a real value. | `tests/unit/test_repo_artifacts.py` |
| 5 | `docs/runbook.md` | How to operate it, and how it fails. A failure mode nobody wrote down is discovered in production. | review |
| 6 | `COMPLIANCE.md` | Change the affected row's status if this adapter closes or opens a control. | review |

Then run `make gate`. The contract suite picks the new adapter up automatically: it is
constructed, checked against its Protocol, built again in a fresh interpreter with the cloud
SDKs unimportable, and driven with the canonical call for its port.

If the adapter belongs to the `local` family, check it still ANSWERS rather than merely not
raising: `tests/contract/canonical.py` defines what answering means for that port, and a local
adapter that quietly returns nothing is the failure mode that ships a green gate with no
working profile.

## Walkthrough: adding a PORT or a sub-service

A port lives in five places at once. Four of the five can be satisfied while the fifth is
missing, and the result is a port with zero enforcement and a green build, so
`tests/contract/test_port_parity.py::test_every_home_of_the_port_set_agrees_exactly` asserts set
equality across all five. That test is the reason this list is exhaustive rather than indicative.

| # | File | What to add | Enforced by |
|---|---|---|---|
| 1 | `src/contract_obligation_extraction/ports/<port>.py` | The `@runtime_checkable` Protocol. Name the boundary, not the implementation. | `test_port_parity.py` conformance tests |
| 2 | `src/contract_obligation_extraction/ports/__init__.py` | Import it, add it to `PORT_PROTOCOLS` and to `__all__`, so there is one import site. | the drift guard (home 1) |
| 3 | `src/contract_obligation_extraction/config.py` | An entry in `DEFAULT_BINDINGS` binding ALL THREE profiles, plus one `cached_property` on `Container` that asserts the Protocol. | the drift guard (homes 2 and 4) |
| 4 | `config/settings.yaml` | The same three bindings under `adapters.<port>`. | the drift guard (home 3) |
| 5 | `src/contract_obligation_extraction/adapters/{local,gcp,onprem}/<port>.py` | Three adapters. `local` WORKS offline, `gcp` imports its SDK lazily, `onprem` RAISES `NotImplementedError`. A placeholder that returns successfully is a false portability claim; one that raises a bare `NotImplementedError` on a SERVING path answers 500 with no body, so raise a subclass that also carries a status and a reason (see `adapters/onprem/identity.py`). | `test_behavioral_parity.py` |
| 6 | `tests/contract/canonical.py` | A `PortCase`: the canonical `invoke`, what `answered` means, and the managed family's documented refusal. | the drift guard (home 5) |
| 7 | `tests/unit/test_<feature>.py` | What the port is FOR. The contract suite proves the shape; only this proves the behaviour. | review |
| 8 | `api/app.py`, `cli/main.py`, `agent/tools.py` | Wire the new capability into every surface that should expose it. A capability on one surface out of three is a capability that behaves differently depending on how it is called. | review |
| 9 | `agent/agent_card.py` | If it becomes an agent tool, add the matching skill. The card and the tool table are compared for set equality. | `tests/unit/test_agent_surface.py` |
| 10 | `ARCHITECTURE.md`, `COMPLIANCE.md`, `docs/runbook.md` | The port table, the affected principle or rule row, and how to operate it. | review |

A **sub-service** (a new deterministic engine in `domain/`) follows the same shape with two
additions: the consequential decision stays pure stdlib and replayable (a model may narrate it,
never produce it), and every consequential result it produces escalates through
`ReviewRouterPort` rather than terminating in a boolean.

## Before you open the change

```sh
make gate          # the offline hard gate: everything above
make audit         # pip-audit over both lockfiles (needs network; CI runs the same)
make test-integration   # only if you touched a managed adapter and have the configuration
```

Update `docs/practices-audit.md` when a check's verdict changes. It is the file that records
what this repo owes, and a GAP that quietly became a PASS is as misleading as the reverse.
