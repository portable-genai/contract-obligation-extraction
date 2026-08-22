# Reusable skills: building a comprehensive agentic repo for any domain

These skills distill the methodology used to build this reference repo into a domain-
agnostic playbook. They are plain Agent Skills (`SKILL.md` with YAML frontmatter), so drop the
directory in as `.agents/skills/`, the portable Agent Skills location, and use them to build a
comparably comprehensive
system for a different purpose: **campaign planning, ad-creative generation, performance
marketing, online-retailer recommendations**, or anything else with the same shape.

The "shape" they assume: an agentic / decision-support system that touches external services
(an LLM, data stores, search, external APIs), must stay testable and portable, makes
consequential decisions that need to be explainable and human-reviewed, and is delivered
feature-by-feature.

## The skills

| Skill | Use it to |
|---|---|
| **find-next-priorities** | Identify the next evidence-backed portfolio work from the current OKF concepts, portfolio backlog, authoritative system rows, audit evidence and mandatory dependencies without creating another status snapshot. |
| **ports-and-adapters-repo** | Scaffold the whole repo: a pure-stdlib domain core, typed ports, swappable adapter profiles (cloud / offline / exit), a DI container driven by one settings file, and a green offline gate. **Start here.** |
| **deterministic-domain-service** | Implement each feature's consequential logic as a pure, replayable, unit-tested service (the LLM only narrates): outputs cite evidence, escalate softly to a human, redact PII before the model, and validate the model's output against a schema. |
| **audit-first-demo** | Build the explainable output view, a dependency-free HTML renderer, a synthetic-data demo, screenshots, and an immutable content-free audit record, so every feature is verifiable and demoable. |
| **vertical-slice-delivery** | Grow the repo feature-by-feature: analyze gaps, choose scope via `AskUserQuestion`, ship one end-to-end slice per green PR, watch CI, merge, repeat. |
| **iterative-code-review** | Converge a change to correctness with an independent reviewer -> fix + regression test -> re-review loop, before each PR/merge. |
| **embeddable-secure-ui** | Make the UI a portable micro-frontend that embeds into a client's existing web app (or runs standalone) with profile-gated identity: local dev personas (no IdP), GCP IAP-verified assertion in secure mode, server-side `IdentityPort` that discards any client-asserted actor/ACL, same-origin reverse-proxy + embed mode, CSP frame-ancestors + per-tenant CORS, and a client integration guide. |
| **deploy-and-residency-hardening** | Make the deployed posture enforceable: a Dockerfile + infra/terraform that pins data residency to an in-country region, applies Org Policy, binds CMEK end to end, stands up a dry-run-first VPC-SC perimeter, writes WORM audit logs, and alerts on posture violations. |

## How they fit together

```
ports-and-adapters-repo            (once: scaffold + conventions + gate)
        │
        ▼
vertical-slice-delivery            (the loop, repeated per feature)
        ├── deterministic-domain-service   (the engine for the slice)
        ├── audit-first-demo               (the output view + demo for the slice)
        └── iterative-code-review          (converge correctness before the PR)
        │
        ▼
deploy-and-residency-hardening     (make it deployable + compliant once it has features)
```

## The transferable principles (true in every domain)

1. **Hexagonal core.** The domain is pure stdlib; everything external is a port with
   swappable adapters selected by a one-line profile switch. Testable offline, portable
   across vendors.
2. **Determinism where it counts.** Consequential math/decisions are pure code an auditor
   can re-run and a test can pin. The LLM only narrates, drafts, or classifies, and never
   produces the number that matters.
3. **Explainable, human-in-the-loop output.** Every claim cites its evidence; consequential
   results escalate softly to a reviewer instead of auto-executing.
4. **Audit-first, demoable surface.** Output is designed for someone who must verify it, and
   it runs end-to-end offline on synthetic data.
5. **Vertical slices behind a green gate.** Each feature ships as one small PR that leaves
   `main` releasable; scope is steered between slices via `AskUserQuestion`.
6. **Converge correctness.** An independent review loop, not a single pass, before merge.
7. **Profile-gated data.** Local fixtures and offline CI use obviously fictional data. An
   opt-in live profile may use public or audience-provided data only with explicit sign-off,
   custody controls, tenant authorization and no silent fallback to fixtures.

Adapt the nouns to your domain; keep the principles.

## Shared conventions (apply to every repo)

These cross-cutting rules hold across the whole catalog, on top of the per-skill guidance.

### Canonical location
These skills are maintained centrally and vendored into each system repo under its own
`.agents/skills/`. A vendored copy is generated: edits made to it are overwritten on the next
sync, so fix the canonical copy instead.

Two of them are **org-level and are never vendored**: `find-next-priorities` and
`ports-and-adapters-repo`. The first reads maintainer-only records, and the second creates a
repository rather than working inside one, so both are run centrally. The sync script removes
them from a repo that still holds a copy.

### Absence is not consent, and an emptied variable is not an absent one
Every environment read has THREE states: unset, set-and-empty, set-and-valid. An unset env var,
a variable an operator deliberately emptied, an empty allowlist and a missing binding are all
UNCONFIGURED, never a request for the most permissive behaviour. Read them through the commons'
`read_env_setting`, never `os.environ.get(name, "")`, which collapses the first two states
before any of your logic runs. Every repo resolves its profile exactly once, keeps "nobody
chose" as a state distinct from a chosen `local`, raises at IMPORT on an emptied, unknown or
mis-capitalised value so a misconfiguration is a boot failure, and registers every exposure
guard on the app OBJECT (a `Dockerfile` `CMD` and `make run-api` serve the app object and never
call `main()`). Relaxations and restrictions read DIFFERENT derived profile strings, because
they fail closed in opposite directions. The rule and the reference shape are in
`ports-and-adapters-repo`, under "Resolving the profile"; the working implementation is
`hex-service-template`'s rendered `config.py`.

### A service credential is not end-user authentication
An exposure guard derives its posture from the bound IDENTITY adapter's own declaration, and
from nothing else. A shared secret, an S2S bearer, an API key or a mesh certificate
authenticates a calling SERVICE and authenticates no end user, so it is not evidence that a
route a browser reaches is protected. While one such credential fed a guard in this catalog,
SETTING it switched the guard OFF for the end-user routes it was protecting, and a LAN peer
with no credential got a full seeded persona list and a real decision. See
`ports-and-adapters-repo`, "Posture comes from the identity binding".

### A guard that cannot detect its own defect class is not a guard
Introduce the exact defect a check claims to catch and watch it go RED before trusting it. A
check only ever observed GREEN is indistinguishable from one that asserts nothing. Two proven
in this catalog: a lockfile check asserting 40 hex characters could not tell a commit from an
annotated tag object, and a two-state environment scanner that parsed only Python was blind to
the UI layer where the defect it cited actually lived. A guard must also cover every language
the defect can be written in, not only the one the guard is written in. See
`ports-and-adapters-repo`, "Prove the guard RED first".

### Docs style: no em-dashes
Do not use the em-dash character (U+2014, the long dash) or its HTML entities (`&mdash;`,
`&#8212;`, `&#x2014;`) in any markdown (`.md`) or HTML (`.html`) file, nor in commit messages
or PR bodies. Use a colon, comma, parentheses, or two sentences instead. This applies to
generated HTML too (the `audit-first-demo` renderer output), not only hand-written docs.

### Required per-repo doc/artifact set
Every repo ships the same set so no control is silently dropped: `README`, `SPEC`,
`ARCHITECTURE`, `CONTRIBUTING`, `DEMO.md`, `COMPLIANCE.md`, `docs/runbook.md`,
`docs/onprem-migration.md` (the exit guide), `eval/` (the quality gate), a `Dockerfile`, and
`infra/terraform/`.

### The principle canon
Each repo's `COMPLIANCE.md` maps every General Principle (`P-01`..`P-13`) and dependency rule
(`R1`..`R8`) one-to-one to a concrete control in code, with evidence. The canon itself is
published on [the organization front page](https://github.com/portable-genai); treat it as the governance
backdrop the skills implement: managed-first and minimal surface, no vendor lock-in, in-country
residency, minimise PII to the model, human oversight, maker-checker, audited everything, a
quality/eval gate, CMEK that does not cascade, provenance on every claim, defense in depth, and
exit/portability.
