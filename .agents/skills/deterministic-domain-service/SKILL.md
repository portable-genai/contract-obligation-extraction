---
name: deterministic-domain-service
description: >-
  Implement a feature as a PURE, deterministic, replayable domain service: the
  consequential math/decisions are stdlib-only and unit-tested (same inputs -> same
  result), the LLM only narrates/drafts/classifies, every output cites its evidence, and
  anything consequential escalates softly to a human reviewer instead of auto-executing.
  Use when adding a calculation, scoring, reconciliation, ranking, eligibility, allocation,
  or any decision engine to an agentic repo, in any domain.
---

# Deterministic domain service

The core discipline that keeps an agentic system trustworthy: **never put consequential
math or decisions inside an LLM.** The LLM is non-deterministic and unauditable; your
budget allocation, ROAS calculation, eligibility check, ranking, or gap analysis must be
pure code an auditor can re-run and a test can pin. The LLM's job is narrow: turn the
deterministic result into prose, draft a message, or classify free text, never to decide
the number that matters.

## When to use

- Adding any engine that computes or decides something consequential: a score, a band, a
  reconciliation, an allocation, a ranking, an eligibility/policy check, a gap/anomaly
  detector, a schedule.
- You catch yourself about to ask an LLM to "calculate", "decide", "rank", or "approve".
  Stop and build a deterministic service instead.

## The pattern

1. **A frozen, dependency-free service.**
   ```python
   @dataclass(frozen=True, slots=True)
   class <Feature>Service:
       """Pure, deterministic <feature>. Tolerances/weights configurable."""
       tolerance: float = 0.15            # tunables as fields, not magic numbers

       def assess(self, subject_id, declaration, evidence) -> <Feature>Assessment:
           """Same inputs -> same result. No LLM, no I/O."""
   ```
   No clock reads, no randomness, no network, no file/db access inside the method. If you
   need "now", pass `as_of` in as a parameter (so the result is reproducible and testable).

2. **Severity-ranked, explainable findings.** Output a structured result: the computed
   figures + a tuple of findings/gaps, each with a `severity`, a one-line `summary`, a
   `detail`, and a stable `id`. Rank them deterministically (severity, then id).

3. **Provenance.** Carry citations through: each line/finding references the evidence it
   was derived from, so the output is verifiable.

4. **Soft escalation, never auto-block.** Add an `escalates` property: any finding (or a
   threshold breach) flips the case to "enhanced/human review". The service flags; a human
   disposes. Nothing consequential executes automatically.
   ```python
   @property
   def escalates(self) -> bool:
       return bool(self.findings) or self.status is Status.OVERDUE
   ```

5. **The LLM stays outside.** If narration is needed, the orchestrator calls the LLM port
   AFTER the deterministic result exists, passing the numbers in. The LLM never produces
   the numbers.

6. **Wire it into the orchestrator + output view.** Add an `attach_<feature>` method to the
   orchestrator that loads the case, attaches the assessment (with optimistic concurrency if
   stateful), records an audit decision (ALLOWED vs ESCALATED), and carries the assessment
   into the audit/output view.

7. **Re-export** the service from the `services.py` aggregator so wiring layers have one
   import surface.

## The LLM boundary (govern the narration path)

Determinism keeps the LLM out of the math; these rules keep the LLM from becoming a new risk
on the narration path it does own:

- **Redact before the model.** Run PII / sensitive-data redaction before ANY call that leaves
  the trust boundary (the model, a search index, a registry, the audit log), then redact again
  at the model-boundary callbacks (defense in depth). The model sees the minimum it needs, and
  spans/traces capture no content.
- **Constrain and validate the output.** Ask the model for a declared response schema and
  validate what comes back; on a schema miss, escalate rather than pass it through. Narration
  that fails validation never reaches the user or the audit record.
- **Treat model input as untrusted.** Retrieved documents and user text can carry
  prompt-injection. Keep instructions separate from data, never let retrieved content escalate
  the model's authority, and never let the model trigger a consequential action directly.
- **Degrading means serving LESS, never serving less-verified.** When the model port, the
  retrieval port or an enrichment fails, drop the enrichment or escalate to a human. Never
  substitute unchecked data for checked data, and never skip the check that was itself the thing
  failing. `except Exception: return <permissive default>` around a validation call is a check
  that disables itself precisely when something is wrong.
- **Restating the core rule:** the figure that matters comes from the deterministic service.
  If the prose and the figure ever disagree, the figure wins and the case escalates.

## Tests are the spec (write these every time)

- **Happy path:** fully-evidenced / in-tolerance input -> no findings, `escalates is False`.
- **One test per finding kind:** construct the minimal input that triggers exactly that
  finding; assert its kind/severity/related field.
- **Ranking:** assert higher severities precede lower.
- **Boundary conditions:** exactly-at-threshold, zero, empty inputs, missing optional data.
- **Determinism:** call twice, assert identical stable output (compare ids/figures, not
  timestamp fields).
- **Defaults / fallbacks, in THREE states.** A tunable that was never configured takes the
  documented default. A tunable an operator deliberately EMPTIED is not the same thing: an
  intent was expressed and it names nothing, so it must refuse rather than inherit the unset
  default. Read every environment-sourced knob through `read_env_setting`, never
  `os.environ.get(name, "")` (`ports-and-adapters-repo`, "Resolving the profile"). This bites
  hardest where the default is the permissive one: an emptied tolerance, an emptied threshold
  or an emptied rule list that silently reverts to the shipped value is a policy change nobody
  reviewed.
- **Escalation is the default, not the fallback.** Assert that a service which cannot evaluate
  a rule ESCALATES. A missing input, an unparseable figure or an absent reference must never
  resolve to "no finding": absence of evidence of a problem is not evidence of its absence, and
  a check that quietly skips itself is a check that passed everything.
- **Prove each test RED.** Mutate the service so the finding it asserts should stop firing, run
  the test, watch it fail, then revert. A test only ever observed GREEN is indistinguishable
  from a test that asserts nothing (`ports-and-adapters-repo`, "Prove the guard RED first").
  And if you are removing a fail-open, find the test that was ASSERTING the old behaviour and
  rewrite it into the regression guard for the fix rather than deleting it.

Keep fixture data obviously fictional.

## Domain examples (same pattern, different nouns)

- **Campaign planning (`BudgetAllocationService`):** splits a total budget across channels
  by weighted objective and audience reach; findings: `OVER_CONCENTRATED`,
  `UNREACHABLE_SEGMENT`, `PACING_RISK`. Deterministic; the LLM only drafts the plan summary.
- **Ad-creative generation (`BrandSafetyService`):** validates a generated variant against
  brand/spec/policy rules; findings: `BANNED_TERM`, `MISSING_DISCLAIMER`, `ASPECT_RATIO`.
  The LLM generates the copy; this service decides whether it may ship; a human approves.
- **Performance marketing (`RoasReconciliationService`):** reconciles spend vs attributed
  revenue against a ROAS target; findings: `BELOW_TARGET`, `ATTRIBUTION_GAP`,
  `BUDGET_OVERRUN`. Bid/budget shifts escalate for human approval, never auto-applied.
- **Retail recommendations (`EligibilityRankingService`):** filters a candidate set by
  inventory/eligibility, then ranks by a transparent score; the LLM only writes the
  "why recommended" blurb from the deterministic score.

## Checklist before you commit

- [ ] No LLM / network / clock / randomness inside the service.
- [ ] Tunables are fields, not literals.
- [ ] Output is structured, severity-ranked, and carries provenance.
- [ ] `escalates` property exists; nothing auto-executes.
- [ ] Wired into the orchestrator + output view; re-exported from `services.py`.
- [ ] LLM boundary: redact before the model, validate its output against a schema, the figure
      stays the service's.
- [ ] Degradation serves LESS, never less-verified; no `except` swallows the check itself.
- [ ] Config knobs read in three states: unset takes the documented default, EMPTIED refuses.
- [ ] Tests: happy path, each finding kind, ranking, boundaries, determinism, defaults,
      escalate-when-it-cannot-evaluate.
- [ ] Every new test proven RED on a deliberate mutant before it was trusted.
- [ ] Full gate green.

**Docs style:** no em-dashes in `.md` or `.html` files, commit messages, or PR bodies. See
`skills/README.md`.
