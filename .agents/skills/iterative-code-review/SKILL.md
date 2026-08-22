---
name: iterative-code-review
description: >-
  Run a converging code-review loop on a change: spawn an INDEPENDENT reviewer to hunt real
  bugs and edge cases (not style, since the gate covers that), triage findings, fix the genuine
  ones, add tests for them, then re-review until a pass comes back clean. Use after building
  a feature/slice and before opening or merging a PR, or whenever asked to "review and fix
  the issues until they're fixed".
---

# Iterative code-review loop

Tests pin the behavior you thought of; an independent review finds the behavior you didn't.
This loop adds a cheap, high-signal adversarial pass on a change and drives it to
convergence: issues found AND fixed AND re-verified, not just listed.

## When to use

- After implementing a feature or vertical slice, before the PR (or before merge).
- When the user says "do iterative code review and fix the issues until fixed".
- After a non-trivial refactor or bug fix where edge cases lurk.

## The loop

### 1. Independent review pass

Spawn a fresh reviewer (a subagent) with **no stake** in the code, pointed at the specific
new/changed files. Give it sharp instructions:

- Find **real correctness bugs and edge cases**, not style nits (ruff/mypy/format already
  pass; say so, so it doesn't waste effort there).
- Call out the specific risk areas for this change: date/number arithmetic, boundary
  conditions (zero/empty/exactly-at-threshold), None-handling, precedence of conditions,
  off-by-one, duplication/guard logic, serialization mismatches, and **test coverage gaps**.
- Require each finding as `file:line · severity (bug/edge-case/minor) · concrete description
  · suggested fix`. Tell it to **verify claims** (e.g. actually compute the dates) and to
  not pad: if something is fine, stay silent.
- Tell it **not to edit**, just report.

### 2. Triage

Sort findings into: genuine bugs (fix now), worthwhile robustness/coverage improvements (fix
if cheap and in-scope), and intended-design / false-positive (note why, no action). Don't
reflexively act on every item: a finding can be wrong; judge it.

### 3. Fix + add tests

For each accepted finding: make the fix, and add a regression test that would have caught it
(the test is how you prove it's fixed and keep it fixed). Re-run the full gate.

### 4. Re-review until clean

Run another independent pass focused on the diff since the last review: confirm each fix is
correct and complete, and scan for anything the fix introduced (a new bug, new duplication,
wrong precedence). Repeat 2-4 until a pass comes back with no actionable findings. That is
convergence.

### 5. Report

Summarize: issues found, which were fixed (with the regression tests added), which were
intentional/declined and why, and the final gate result. Then proceed to the PR/merge.

## What good findings look like (calibration)

From a real run of this loop:
- **Bug:** "empty `last_reviewed` yields DUE_SOON with days=0 and does not escalate; a
  never-reviewed case is the highest priority; should be OVERDUE + escalate." -> fixed +
  test `test_never_reviewed_is_overdue_and_escalates`.
- **Edge-case:** "the schedule note is dropped when an event trigger co-occurs." -> always
  record the note + test.
- **Minor:** "render uses hard subscripts `t['severity']`; rest of file uses `.get()`." ->
  defensive `.get()`.
- **Declined (intended):** "`escalates` is redundant with the OVERDUE check", harmless and
  deliberate; noted, no change.

## Tips

- Keep the reviewer's scope tight (the changed files), and give it the domain context in one
  paragraph so it judges intent correctly.
- Let it run code to verify: a reviewer that computes the boundary case beats one that
  guesses.
- The loop is done when a clean pass returns, not after one round of fixes.
- Have the reviewer confirm the gate passed with no cloud SDK installed (the portability
  invariant), not just that it is green on a developer machine.
- **A green gate is evidence about what the gate tests, and nothing else.** Say so to the
  reviewer. The catalog's one CRITICAL exposure defect sat under a fully green suite because
  every test in it talked to loopback, the one peer the exposure guard always admits. Ask the
  reviewer what the suite structurally CANNOT observe, and go observe that by hand.
- **Attack the artifact, do not only read it.** Run the thing from where an attacker would be:
  a real LAN peer, an unset environment variable, a deliberately emptied one, a credential
  present that should change nothing. Reading a diff finds logic errors; only exercising the
  built artifact finds a posture that was derived from the wrong input.
- **Ask the reviewer to mutate each new guard and confirm it goes RED.** A check nobody has
  seen fail is indistinguishable from a check that asserts nothing, and both look identical in
  a diff. Two shipped examples: a lockfile check asserting 40 hex characters could not tell a
  commit from an annotated tag object, and an environment scanner that parsed only Python was
  blind to the UI layer where the defect it cited actually lived.
- **When a fix removes a fail-open, hunt the test that was PINNING it.** A test asserting the
  old permissive behaviour turns the correct fix into a red build; rewriting it into the
  regression guard for the fix is part of the fix, not follow-up work.

**Docs style:** no em-dashes in `.md` or `.html` files, commit messages, or PR bodies. See
`skills/README.md`.
