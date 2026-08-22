---
name: vertical-slice-delivery
description: >-
  Deliver a comprehensive repo feature-by-feature as isolated vertical slices: analyze
  what's missing, use AskUserQuestion to let the user choose scope, implement ONE slice
  end-to-end (model -> service -> orchestrator -> output view -> demo -> docs -> tests),
  get the gate green, open a PR per slice, watch CI, and merge when green, then repeat.
  Use when building out a multi-feature system over many iterations, or when the user says
  "what else is missing", "add the next feature", or "continue".
---

# Vertical-slice delivery

How to grow a repo into something comprehensive without a big-bang rewrite: each feature is
one **vertical slice** that goes all the way from domain model to a demoable output, ships
as its own green PR, and leaves `main` releasable at every step. This is the delivery loop
that complements the `ports-and-adapters-repo` architecture and the
`deterministic-domain-service` pattern.

## The loop

### 1. Analyze, then let the user decide scope

When asked "what's missing" or "what next", first do a real gap analysis against the
domain's standards/best-practices and the current code. Then **use the `AskUserQuestion`
tool** to turn your analysis into concrete choices; do not silently pick. Good questions:

- Which feature(s) to build next (offer the analyzed options; allow multi-select).
- A consequential design fork (e.g. "hard-block vs soft-escalate?", "live calls vs synced
  snapshot?", "scheduled pull vs event-driven?").
- Reference-data / integration approach where it materially changes the design.

Investigate any sub-question the user raises (e.g. "check if X can be synced") with real
sources before re-asking. Once you have clarity, implement.

### 2. Implement ONE slice, end to end

A slice is not done until every layer is touched:

1. **Domain model**: new frozen dataclasses in `models.py`; add the new optional field to
   the case/result aggregate and the output view.
2. **Deterministic service**: build it with the `deterministic-domain-service` skill.
3. **Orchestrator wiring**: an `attach_<feature>` method; carry the field through analyze.
4. **Output view + renderer**: a new panel (use the `audit-first-demo` skill).
5. **Demo**: wire the feature into the synthetic demo script so it's runnable.
6. **Docs**: a new design-doc section and a DEMO section; if the slice adds a port, add a
   row (named) to the architecture port table and a binding to `settings.yaml`, and update
   the COMPLIANCE.md control map if it adds or changes a control. Do NOT bump a hardcoded
   count anywhere ("the N ports", "13 Protocols"): those rot silently as slices land. The
   `ports/__init__.py` `__all__` plus the parity test are the source of truth for the count;
   docs enumerate by name (one row per port), never by number. Also update the scripts README
   if scripts changed. Write the docs, the commit message, and the PR body in plain prose
   (docs style at the foot of this skill).
7. **Tests**: unit tests for the service (the spec); update contract tests if a port was
   added.

Keep slices small and independent. If a feature is big, split it into sub-slices that each
ship green.

### 3. Get the gate green locally

Run the full gate (`ruff check`, `ruff format --check`, `mypy`, `pytest -m 'not
integration'`, `python eval/run_eval.py`) and fix until clean. Pin the linter version so
local matches CI. Re-render the demo / re-take screenshots if the output changed.

### 4. Review before you ship

Run the `iterative-code-review` pass (independent reviewer -> fix -> re-verify until
converged) on the slice. Cheap, and it catches the edge cases tests miss.

### 5. One PR per slice; watch CI; merge when green

- Branch per slice (e.g. `feat/<slice-name>`), never push straight to the default branch.
- Commit with a clear message: what + why + the gate result. Honor the user's authorship
  preferences exactly (e.g. single author, no co-author trailers, if they asked).
- Push, open a PR **ready for review** (not draft), with a body that lists the changes, a
  table of any new finding/trigger kinds, and the gate status.
- Watch CI. Webhooks deliver failures but NOT success, so after pushing, re-check CI status
  explicitly (or arm a timed self check-in) and merge (squash) when all checks are green, per
  the user's standing instruction.
- After merge, sync `main` and start the next slice.

### 6. Repeat until the selected scope is done

Track the selected features as a checklist; report status after each slice (done /
in-flight / pending). Surface housekeeping that needs the user (e.g. deleting merged remote
branches if the tooling can't).

## Why slices (not one mega-PR)

- Each PR is small enough to review properly and revert cleanly.
- `main` is always green and demoable.
- The user steers scope between slices instead of after a huge diff.
- The architecture (pure domain + ports) makes slices genuinely independent: a new service
  + a new optional field rarely touches existing code.

## Worked example (any domain)

Performance-marketing repo, after the scaffold:
1. Analyze gaps -> AskUserQuestion: "Which next? [attribution view] [bid optimizer]
   [budget pacing] [anomaly alerts]" (multi-select) + "Apply changes automatically or
   escalate for approval?"
2. User picks pacing + anomaly alerts, soft-escalate.
3. Slice 1 = budget-pacing service (deterministic) -> orchestrator -> pacing panel -> demo
   -> docs -> tests -> gate -> review -> PR -> merge.
4. Slice 2 = anomaly-alert service, same loop.
5. Report: pacing ✅ merged, anomaly ✅ merged; suggest next candidates.

## Checklist per slice

- [ ] Gap analysis done; scope chosen via AskUserQuestion (not silently).
- [ ] All layers touched: model, service, orchestrator, view/renderer, demo, docs, tests.
- [ ] Full gate green locally; demo/screenshots refreshed.
- [ ] Iterative code review converged.
- [ ] Branch per slice; commit message honors authorship prefs.
- [ ] PR ready-for-review with a descriptive body; CI watched; merged when green.
- [ ] Status reported; next candidates surfaced.

**Docs style:** no em-dashes in `.md` or `.html` files, commit messages, or PR bodies. See
`skills/README.md`.
