---
name: embeddable-secure-ui
description: >-
  Make a hexagonal agent's UI a portable, secure micro-frontend that embeds into a client's
  EXISTING web app (or runs standalone) with profile-gated identity: local = seeded dev
  personas with NO IdP/AD/LDAP (offline demo/test), secure = verify the GCP IAP-injected
  assertion (auth configured ON the service), onprem = client IdP placeholder. Adds a server
  -side IdentityPort that DISCARDS any client-asserted actor/ACL, a same-origin reverse-proxy
  + embed mode, CSP frame-ancestors + per-tenant CORS, and a client integration guide. Use
  when asked to make the UI embeddable/portable, add SSO/identity passthrough, harden auth,
  or "do what we did in cdd-sow-research" to another catalog repo.
---

# Embeddable, secure micro-frontend (profile-gated identity)

A repeatable playbook for turning a catalog agent (hexagonal Python backend + Next.js `ui/`)
into a **client-deployable component**: its UI drops into the customer's existing web app with
the user journey intact and secure SSO, and its backend enforces per-user identity server-side
instead of trusting a client-supplied `actor`. Reference implementation: `cdd-sow-research`.

Pair this with `ports-and-adapters-repo` (the architecture it extends) and
`vertical-slice-delivery` (deliver it as one gate-green slice per repo).

## Applicability

Use this pattern for a system with an end-user UI. Per-system rollout status is tracked outside
this document; this reusable skill is not a rollout tracker. Do not claim a repo enforces
server-side identity until its body `actor` field is gone and the contract test covers
`identity`. Cross-origin modes and standalone OIDC remain separate hardening slices rather than
implicit parts of this baseline.

## Decisions baked in (do not re-litigate)
- **Identity pattern:** the app is fronted by **GCP Identity-Aware Proxy (IAP)** in secure mode;
  the backend VERIFIES the injected `x-goog-iap-jwt-assertion` (auth configured on the GCP
  service, least app code). Per-hop OAuth2 token-exchange (OBO) + Workload Identity to the Hrz
  services is the next hardening layer (document it; do not build it in this slice).
- **Isolation/transport:** **same-origin reverse-proxy** (serve the agent under the parent
  origin, e.g. `portal.client.com/agent/*`) so the iframe is first-party (no third-party-cookie
  problem, no CORS), plus a **standalone** deployment when there is no host app.
- **PEP:** defense-in-depth (edge IAP/Apigee -> Hrz1 guardrail -> per-backend re-validation).
- **Local mode runs with NO auth** (seeded dev personas) so demos and tests stay offline and
  SDK-free, exactly like the rest of the catalog. Because it is the permissive posture, it is
  entered only by NAMING it: an unset profile variable gets the offline adapters and none of the
  offline permissions (`ports-and-adapters-repo`, "Resolving the profile").
- The server **never trusts a client-asserted `actor`/ACL**; the verified `Principal` supplies
  the audit actor and the entitlement principals fed into governed retrieval.
- **The identity BINDING is what says whether end-user routes are authenticated.** Not the
  profile string, and never a service credential. See "The one thing that may relax the exposure
  guard" below; it is the CRITICAL defect this skill exists to keep out of the next repo.

## The pattern, layer by layer

### 1. Domain identity types (pure stdlib)
`src/<pkg>/domain/identity.py`: `Principal(subject, principals, tenant, assurance, source)` with
`actor` property == `subject`; `RequestContext(headers)` with case-insensitive `header(name)`;
`IdentityError(Exception)`; an `ANONYMOUS` constant used only where an adapter explicitly opts
out (never the secure default).

### 2. The port, and what an adapter DECLARES about itself
`src/<pkg>/ports/identity.py`: `@runtime_checkable class IdentityPort(Protocol)` with
`resolve(self, ctx: RequestContext) -> Principal`. Export it from `ports/__init__.py` (import +
`__all__`).

The same module carries the declaration the exposure guard reads: a class attribute
(`end_user_auth`) set to `VERIFIED` (the adapter checks a server-side assertion's signature,
issuer and expiry, so a caller cannot name itself), `CLIENT_ASSERTED` (the adapter believes a
header the client wrote, which is useful offline and is not authentication) or `UNIMPLEMENTED`
(the adapter resolves nobody). It is a CLASS attribute, not an instance one, because the posture
must be readable WITHOUT constructing the adapter: the seeded-persona adapter refuses to
construct under an inherited profile, and a posture obtainable only by constructing something
disappears in exactly the case it has to describe. An adapter that declares nothing, or declares
a typo, reads as `CLIENT_ASSERTED`: silence is not a claim to verify anything, and a guard that
reads silence as "authenticated" switches itself off for every adapter somebody forgot to
annotate.

### 3. Three profile adapters (mirror the existing adapter families)
- `adapters/local/identity.py` `LocalPersonaIdentityAdapter`: seeded personas (analyst /
  approver / auditor / **other-tenant**), selected by the `X-Dev-Persona` header, default =
  first persona, unknown id -> `IdentityError`. Add a `personas()` lister for the picker.
  Include a cross-tenant persona so per-user/per-tenant authZ is demoable offline.
  This adapter hands out an unauthenticated identity, so it must REFUSE TO CONSTRUCT unless the
  local profile was chosen deliberately: read the `explicit` flag off the resolved profile
  (`ports-and-adapters-repo`, "Resolving the profile") and raise when it is False. A service
  whose profile variable simply went missing must not start handing out an approver persona.
- `adapters/gcp/iap_identity.py` `IapIdentityAdapter`: verify the IAP assertion with **lazy**
  `google.oauth2.id_token` / `google.auth.transport.requests` imports (keeps SDK-free profiles
  import-clean, mirrors the other gcp adapters). Audience from `<PKG>_IAP_AUDIENCE`; derive
  `subject` from `email`/`sub`, `tenant` from `hd`; never log the assertion; any failure ->
  `IdentityError`.
- `adapters/onprem/identity.py` `OnPremIdentityAdapter`: fail-fast `NotImplementedError`
  placeholder for the client's own IdP (OIDC/SAML).

### 4. Wire identity into config
- `config.py` `Container`: add a `identity` cached_property (`self._bind("identity")`).
- `config/settings.yaml` under `adapters:` add an `identity:` block binding `gcp` + `platform`
  to the IAP adapter, `local` to the persona adapter, `onprem` to the placeholder. (The contract
  test requires `local` AND `onprem` bindings for every port.)

### 5. Server-side enforcement at the API boundary
- `api/security.py`: `get_principal(request: Request) -> Principal` builds a `RequestContext`
  from lower-cased headers, calls `deps.get_container().identity.resolve(ctx)`, maps
  `IdentityError -> HTTPException(401)`. Export `CurrentPrincipal = Annotated[Principal, Depends(get_principal)]`.
- `api/app.py`: add `principal: CurrentPrincipal` to every route; pass `actor=principal.actor`
  (and `principals=principal.principals` where the service consumes them); **remove the `actor`
  field from the request schemas** so any client-supplied identity is ignored.
- Domain service: thread the verified principals into governed retrieval, e.g.
  `acl_principals=(*case_acl_tags, *principals)`, so the data path is scoped to what the user
  may see. Keep `actor` as the audit subject. Add `principals: tuple[str, ...] = ()` as an
  optional param so existing callers/tests are unaffected.

### 6. Embedding-surface controls (api/app.py)
- Replace the dev-only wildcard CORS: explicit `allow_methods`/`allow_headers` and an
  env-driven per-tenant origin allowlist `<PKG>_CORS_ORIGINS`, never `"*"`. The localhost
  dev-origin fallback and the `X-Dev-Persona` allowed header are RELAXATIONS, so key both off
  the `exposure_profile` from the resolved profile, not off the raw string: with the profile
  variable unset there is no dev origin and no persona header, and a secure deploy that forgets
  the env var gets an empty allowlist rather than blanket local trust.
- Read every one of these variables in THREE states (`hex_service_kit.netdefaults`
  `read_env_setting`), never `os.environ.get(name, "")`. UNSET takes the documented restrictive
  default; SET-AND-EMPTY names nobody and therefore ADMITS nobody, and must not inherit the
  unset default. An allowlist an operator deliberately emptied that silently reverts to the
  built-in dev origins is the fail-open this whole section is guarding.
- Add an HTTP middleware emitting `Content-Security-Policy: frame-ancestors <allowlist>` from
  `<PKG>_FRAME_ANCESTORS` (unset defaults to `'self'`, emptied refuses, `*` is never accepted),
  plus `X-Frame-Options: SAMEORIGIN` only when the allowlist is `'self'` (CSP wins for
  multi-origin). Emit HSTS on every `exposure_profile` other than a deliberately chosen `local`,
  so an unconfigured service still gets it.
- Register these on the `app` OBJECT at module scope, alongside the loopback exposure guard,
  never inside `main()`: the Dockerfile `CMD` and `make run-api` serve the app object directly.
- Add `GET /v1/personas` (returns the local persona list via duck-typed `getattr(identity,
  "personas", None)`) for the UI picker. It returns empty for every `exposure_profile` other
  than a deliberately chosen `local`, which covers both the secure profiles and the
  unconfigured case.

### 6a. The one thing that may relax the exposure guard: the identity BINDING
The loopback exposure guard bounds routes that answer an END USER. It may relax only when the
adapter bound to the identity port declares `VERIFIED` and the profile was chosen deliberately.
Nothing else may enter that decision, and one thing in particular may never enter it:

> `<PKG>_S2S_TOKEN` (or any API key, mesh identity or shared secret) authenticates a calling
> SERVICE and authenticates no end user. Its presence is not evidence that `/v1/<action>` is
> protected.

This shipped. The catalog template derived the guard from the profile string plus the presence
of the S2S secret, so SETTING the credential DISABLED the guard for exactly the end-user routes
it was protecting. A zero-edit render attacked from a real LAN peer handed an uncredentialed
caller the full seeded persona list and a real decision from the consequential route, with every
offline test green. Read the declaration off the adapter CLASS the active binding names (which
also answers the on-premises path correctly: a deployment that rebound the identity port in
`config/settings.yaml` to the client's own IdP is told about the adapter it ACTUALLY runs), and
resolve any failure to establish the answer to `CLIENT_ASSERTED`. A guard that switches off
because a lookup raised is a guard that fails open.

### 6b. Three-state environment reads in the UI, enforced in the UI's own language
The Python AST scanner that catches two-state `os.environ.get` reads never opens a `.mjs`. That
is not a hypothetical gap either: `env.UI_TENANT_ORIGINS || "*"` survived an entire green gate,
a wildcard CORS allowlist sitting in the one layer nothing was scanning. So:

- `ui/lib/env-setting.mjs` is the JavaScript twin of `read_env_setting` and the ONLY module
  allowed to touch `env[name]`. It returns the same three states.
- Every UI policy variable goes through it: `UI_PROFILE`, `UI_FRAME_ANCESTORS`,
  `UI_TENANT_ORIGINS`. Unset takes the documented restrictive default; EMPTIED refuses. Neither
  ever resolves to `"*"`.
- `next.config.mjs` resolves the embedding policy at MODULE scope, so an emptied allowlist is a
  build and boot refusal rather than a surprise on some later request.
- Ship `ui/tests/three-state-env-reads.test.mjs`: it scans every shipped `.mjs`/`.js`/`.ts`/
  `.tsx` under `ui/` with the same rule and the same two escapes (an exact-match comparison
  against a literal, or a variable listed with a written reason), and it carries the exact
  mutant as a self-proof so the scanner is known to go RED. Wire it into `npm test`, the UI CI
  job, and the render verification. The one deliberate exception is an OUTBOUND service
  credential, exempted with a written reason, because the RECEIVER decides whether an
  uncredentialed call is acceptable.
- Keep the security decisions in plain JavaScript policy modules (`embed-policy.mjs`,
  `identity-policy.mjs`) behind a typed seam, so `npm test` exercises them in bare node rather
  than only through a build.

### 7. UI (ui/)
- `lib/types.ts`: remove `actor` from the request type.
- `lib/api.ts`: drop `actor`; add module-level `devPersona` + `setDevPersona/getDevPersona`;
  attach `X-Dev-Persona` only when set; add `listPersonas()`; keep `health()`.
- `app/page.tsx`: remove the hardcoded actor; add a "Demo identity" persona picker that renders
  ONLY when the health endpoint reports a deliberately chosen local profile (calls
  `listPersonas()`, default-selects + sets the first persona). Have `/healthz` report the
  `exposure_profile`, so an unset profile variable reports `unconfigured` and the picker stays
  hidden; a placeholder `"local"` in the health handler is the same absence-read-as-consent
  defect wearing a different hat.
- `app/layout.tsx`: EMBED mode, when `process.env.NEXT_PUBLIC_EMBED === "1"` render children
  without the app header/chrome so the host owns the chrome. (An exact-match comparison against
  a literal is the one two-state read that is safe: it neither takes a default nor grants.)
- `next.config.mjs`: `basePath`/`assetPrefix` from `NEXT_PUBLIC_BASE_PATH` (blank => standalone
  unchanged) so it can mount under a reverse-proxy sub-path.
- **The browser never asserts who it is.** Every client-supplied actor, tenant, role, ACL and
  `Authorization` header is DISCARDED before the request is forwarded; identity is resolved
  server-side; the service credential stays on the server and is never shipped to the browser
  (a `NEXT_PUBLIC_*` variable is public by construction, so a secret must never be one).

### 7a. The document CSP must be nonce-based, and the page must be able to CARRY the nonce
A console that ships `script-src 'self'` serves DEAD MARKUP. Next serves
its hydration bootstrap as an INLINE script, so a bare `'self'` blocks it: `__next_f` never
fills, React never attaches, and the page is a static picture of a console. For an embeddable
micro-frontend that is total failure, and it is invisible to every cheap check. The headers are
correct. `tsc` is clean. The production build succeeds. The policy unit tests pass. The page
renders and screenshots fine.

Three things must ALL be true, and any two of them is WORSE than none, because `'strict-dynamic'`
switches off the `'self'` fallback that was at least loading the chunk scripts:

- The policy module emits `script-src 'self' 'nonce-<n>' 'strict-dynamic'` when given a nonce,
  and plain `'self'` when not (a response carrying no document needs no nonce).
- `proxy.ts` mints one nonce per request and sets it on the **REQUEST** `Content-Security-Policy`
  header. That exact header name is the only place Next reads a nonce from; a custom name like
  `x-nonce` is silently ignored.
- `app/layout.tsx` sets `export const dynamic = "force-dynamic"`. A statically prerendered route
  was built before the nonce existed, so nothing in its HTML can carry one. An embeddable console
  resolves identity per request anyway, so a static render was never safe across tenants.

`'unsafe-inline'` is NOT the fix. It hydrates, and it also lets any injected inline script run,
which is the whole thing the policy is for.

Emit the policy from ONE layer. A static `headers()` table cannot express a per-request value, so
when the nonce arrives the policy has to move out of `next.config.mjs` and into the module the
proxy uses. Setting it in both places hands the browser two policies to intersect and the
stricter wins, which quietly reinstates the defect.

Two refusals hold it, and both have been made to go red on purpose:
- `assertHydratableCsp(readFileSync("app/layout.tsx"))` called at module scope in
  `next.config.mjs`, so a layout that loses `force-dynamic` fails `next build` and `next start`.
- `ui/scripts/assert-hydratable.mjs`, run by the ui gate after the build: it starts the built
  server, fetches the document and asserts every `<script>` tag carries the served nonce. This is
  the only check that can see the defect, because it is the only one that executes the page.

### 8. Tests (keep the hard gate green)
- Add `identity` to the contract test `PORT_PROTOCOLS` (it auto-checks local+onprem construct
  SDK-free and conform).
- `tests/unit/test_identity.py`: default persona, header selection, unknown -> `IdentityError`,
  persona listing, onprem fails fast, and the local adapter REFUSING to construct when the
  profile was merely inherited.
- Add a test that the verified user's principals reach governed retrieval (request both the
  service fixture and the KB fixture so they share one instance; assert the user principal and
  a `case:` tag are both in the recorded query).
- `tests/unit/test_end_user_auth_posture.py`: expand the guard's authenticated/not argument
  through the module constants it names, at every depth, and fail the build if any service
  credential reappears in it.
- `tests/unit/test_serving_path_exposure.py`: boot the app with the profile variable ABSENT and
  an S2S token PRESENT, and assert every route refuses a non-loopback peer.
- **Prove it off loopback.** Offline suites talk to 127.0.0.1, which the guard always admits, so
  they structurally cannot see this defect class. Ship a script that binds a real socket on this
  machine's LAN address and drives the whole matrix (profile x service credential x persona
  header) against it, and run it in render verification. That script, not the unit suite, is what
  found the CRITICAL above.
- Prove each of these RED on a deliberate mutant before trusting it. A check only ever observed
  GREEN is indistinguishable from a check that asserts nothing (`ports-and-adapters-repo`,
  "Prove the guard RED first"). And when you remove a fail-open, find the test that was
  ASSERTING it and rewrite it into the regression guard for the fix.

### 9. Client integration guide
Write `docs/embedding-and-identity.md`: the three deployment shapes (embedded same-origin /
standalone / local-dev), run-locally-no-auth, secure GCP IAP deploy (+ Workforce Identity
Federation to the client IdP), embed-via-reverse-proxy (nginx + Next `rewrites()` + iframe +
frame-ancestors), the identity contract (body actor ignored; verified Principal -> audit actor +
entitlements), and a client-side integration + security checklist.

## Config knobs (env), per repo
`<PKG>_PROFILE` (local|gcp|platform|onprem) · `<PKG>_IAP_AUDIENCE` · `<PKG>_CORS_ORIGINS` ·
`<PKG>_FRAME_ANCESTORS` · `UI_PROFILE` · `UI_FRAME_ANCESTORS` · `UI_TENANT_ORIGINS` ·
`NEXT_PUBLIC_API_BASE` · `NEXT_PUBLIC_BASE_PATH` · `NEXT_PUBLIC_EMBED` ·
`X-Dev-Persona` (local only). Substitute `<PKG>` with the repo's prefix (e.g. `CDD`).

Every one of them is read in three states. UNSET takes the documented restrictive default;
SET-AND-EMPTY refuses rather than inheriting that default; no allowlist among them may ever
resolve to `"*"`.

## Gate (must stay green)
`ruff check src tests` + `ruff format --check src tests` + `mypy src` +
`<PKG>_PROFILE=local pytest -m 'not integration'` + `python eval/run_eval.py` (exit 0). Keep all
GCP imports lazy so the local/onprem profiles stay SDK-free.

The UI has its own required gate, and "the Python gate is green" is NOT evidence about it: a
Python-only gate is how a wildcard CORS allowlist lived in `ui/` through hundreds of passing
tests. Run `npx tsc --noEmit` AND the node test suite (`npm test`), including the UI three-state
scanner, AND `npm run assert-hydratable` against a production build, in the UI CI job. The
last one is not optional and nothing else substitutes for it: a CSP that blocks the page's
own hydration passes tsc, passes every policy unit test and builds clean. If a repo has no user-facing surface, remove `ui/`, its dependabot
ecosystem and its CI job TOGETHER, and hold the three consistent with a test that fails in both
directions.

## Definition of done (per repo)
Identity is server-verified and the body actor is ignored; the exposure guard's posture comes
from the identity BINDING and no credential appears in it at any depth; local runs with no IdP
via the persona picker and only when `local` was chosen deliberately; secure mode verifies the
IAP assertion; the UI embeds same-origin (basePath + embed mode) and runs standalone; CSP
frame-ancestors + per-tenant CORS set, three-state, never `*`; the document CSP is nonce-based
with the route forced dynamic, PROVEN by `npm run assert-hydratable` against a production
build rather than by reading the header; the guide exists; the hard gate and the UI gate are
both green; and the exposure matrix has been proven against a real socket
from off the loopback interface. Then move to the next repo (the scaffold is uniform, so this is
mechanical: see `vertical-slice-delivery`).

## Out of scope for this slice (next hardening layer, document it)
Per-hop OAuth2 token-exchange (OBO) + Workload Identity + mTLS to Hrz1/Hrz2/Hrz5/Hrz3; DPoP /
step-up (acr/amr) for high-value actions; Hrz2 KB tenant-partition + fail-closed ACL; SSRF
egress controls on any fetch-at-runtime pipeline; Trusted Types on the bundles.

**Docs style:** no em-dashes in `.md` or `.html` files, commit messages, or PR bodies. See
`skills/README.md`.
