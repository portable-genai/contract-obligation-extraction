---
name: audit-first-demo
description: >-
  Make every feature explainable and demoable: design an audit-first output view (grouped
  results, the evidence behind each, the computed figures, the gaps/findings, and the
  suggested next actions), render it to dependency-free static HTML panels, drive it with a
  synthetic-data demo script, and capture screenshots. Use when building the output surface
  for a feature, preparing a stakeholder demo, or when asked to "show how this looks".
---

# Audit-first output + demo

A feature nobody can see or verify is half-built. This skill turns a deterministic result
(from `deterministic-domain-service`) into something a stakeholder can read, trust, and run
in a demo, without standing up a frontend.

The principle is **audit-first**: the output is designed for someone who must verify the
decision, not just consume it. It shows the grouped result, the evidence behind each part,
the computed figures, the gaps/findings the system detected, and the concrete next actions,
each traceable to its source.

## The three artifacts

### 1. The audit view (a domain output type)

A single `<Subject>AuditView` dataclass that bundles everything a reviewer needs:

- the headline result + computed figures (e.g. coverage, score, allocation, ranking);
- **groups**: the result broken into meaningful buckets, each with the evidence ids /
  citations that support it;
- **findings/gaps**: what the deterministic engine flagged, severity-ranked;
- **suggested actions**: what to do next (information to request, a fix, an approval);
- the per-feature panels (each slice attaches its own assessment as an optional field).

Keep it serializable to plain JSON (a `to_jsonable` helper) so the renderer and tests can
consume it without importing the domain.

### 2. A dependency-free HTML renderer

A single script that reads the audit view JSON and writes static HTML: **no framework, no
build step, inline CSS.** One `render_<panel>(data)` function per panel; compose them into a
page. This keeps demos reproducible and screenshots trivial. The renderer emits HTML, so the
no-em-dash docs rule applies to its output too (see the foot of this skill).

Renderer conventions that paid off:
- One function per panel; each takes the (possibly `None`) sub-dict and returns `""` when the
  panel does not APPLY to this case, so partially-populated cases still render.
- A small status pill (`CLEARED` / `ENHANCED REVIEW` / `OVERDUE`...) per panel header driven
  by the assessment's `escalates`/status.
- Defensive accessors: `esc()` that coerces `None`->""; `.get()` for every optional field
  (enums serialize to their `.value` string; match on those).
- **A defensive accessor must never make missing evidence look like clean evidence.** An absent
  citation, an absent assessment or an absent status renders as a VISIBLE gap ("no provenance
  recorded", a warning pill), never as an empty cell and never as `CLEARED`. This is an audit
  view: its whole job is to let a human see what was not checked. `data.get("escalates", False)`
  and `data.get("status", "CLEARED")` are the fail-open shape here, because they turn a serializer
  bug or a renamed field into a reassuring page. Default the status pill to the ALARMING value,
  or raise. And render "0 findings because the check ran and found none" differently from
  "0 findings because the check never ran".
- Severity -> color map; provenance rendered as compact "chips" (source id + locator).
- Watch out: in Python f-strings, no backslashes inside the expression; precompute strings.

### 3. A synthetic-data demo script

A script that builds an obviously-fictional scenario, runs the orchestrator + every feature
service, prints a readable trace to stdout, and writes the audit view JSON for the renderer.
This is also your end-to-end smoke test for a slice. Make it deterministic so screenshots
never drift.

Name the demo scripts consistently across repos so they are discoverable: a `<prefix>_demo.py`
(the offline run that writes the JSON), the `render_<subject>.py` renderer, and a
`<prefix>_demo_playwright.py` for the screenshot/presenter variant, with a short
`scripts/README.md` listing them. Same names everywhere, only the prefix changes.

## The durable audit record (operational, not just the view)

The audit VIEW is for a human reading one result; the audit EVENT is the durable proof the
result happened. Every consequential assessment writes one immutable audit event:

- **One event per assessment**, append-only / WORM (write once, read many), carrying the
  decision (e.g. ALLOWED vs ESCALATED), the actor, and the citations, never the raw subject
  content. Redact before you write (see `deterministic-domain-service`).
- **Content-free traces.** Spans and metrics record that work happened and how long it took,
  not what was in it. Never log a credential, an identity assertion, or PII.
- **Local stays offline.** The `local` adapter writes the event to an append-only local store
  (e.g. a SQLite table) so the audit path is exercised in tests; the cloud adapter writes to
  the immutable sink stood up by `deploy-and-residency-hardening`.

## Screenshots (headless, scriptable)

Render the HTML, then screenshot with a headless browser (Playwright). Patterns that work:
- Full-page screenshot for the whole view; per-panel crops via an element selector
  (`xpath=//section[.//h2[contains(text(),'<Panel>')]]`) for focused stakeholder shots.
- Use a fixed viewport + `device_scale_factor=2` for crisp images.
- Send the image to the user as the deliverable; you don't need to commit binaries.

## Optional: a presenter-controlled live demo

For a guided walkthrough, add a tiny local server + a Playwright script that **waits for the
presenter between steps** (so the person demoing controls pacing). Drive a locally running
instance, not production. Keep a `DEMO.md` covering both the offline demo and the
managed-stack demo, with prerequisites and links to setup.

## Domain examples

- **Campaign planning:** panels for channel mix (with the reach/audience evidence behind
  each split), budget lines, the pacing/over-concentration findings, and "segments to
  validate" actions.
- **Ad-creative generation:** panels showing each variant, the brand/spec/policy checks it
  passed or failed (with the rule cited), and "fix before ship" actions.
- **Performance marketing:** panels for ROAS vs target by campaign (with the metric source),
  attribution gaps, and the proposed budget shifts pending human approval.
- **Retail recommendations:** panels for the ranked recommendations, the eligibility/
  inventory evidence per item, filtered-out candidates with reasons, and the "why
  recommended" blurb.

## Checklist

- [ ] An `AuditView` type bundles result + groups(+evidence) + findings + suggested actions.
- [ ] Serializable to plain JSON; each feature attaches an optional panel field.
- [ ] Dependency-free HTML renderer; one defensive function per panel; absent panel -> "".
- [ ] Deterministic synthetic-data demo writes the JSON and prints a readable trace.
- [ ] Screenshots captured headless (full page + per-panel crops) and shared.
- [ ] DEMO.md / presenter script if a live walkthrough is needed.
- [ ] Each assessment writes one immutable, already-redacted, content-free audit event.
- [ ] Only fictional data; demos run offline on the `local` profile.

**Docs style:** no em-dashes in `.md` or `.html` files (including the renderer's HTML output),
commit messages, or PR bodies. See `skills/README.md`.
