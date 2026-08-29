"""The scripted, offline demo: the REAL services, synthetic data, an audit-first output view.

This is the demo as CODE (practices check F1), not a slide deck and not a recording. Every step
below drives the actual triage service, the actual hash-chained audit store and the actual
rule-R8 review router over the ``local`` profile, so a step that stops being true stops passing
rather than stops being mentioned.

Three properties make it worth running in front of somebody:

* **Nothing is faked.** No stub service, no pre-baked JSON. The severity bands, the audit
  records, the routing references and the tamper verdict are produced by the shipped code.
* **It is bounded.** The demo proves an offline, single-process seam. It does not prove
  cross-host deployment, a live console, or the managed profile; those need a cloud project and
  live in ``tests/integration/``.
* **It is replayable.** Same inputs, same output, every time, because the consequential decision
  is deterministic. That is what makes it safe to run live.

Run it directly to write the audit-view JSON, then render that JSON to static pages::

    make demo-static

or drive it one step at a time with ``demo_server.py`` and ``walkthrough.py`` (``make demo``).

Every party, address and identifier here is obviously fictional: ``.example`` domains, RFC 5737
and RFC 3849 literals, and a synthetic national id that exists only to prove redaction happened.

MAINTAINER NOTE: this file is rendered from a template, so no line may change length with the
package or service name. Every cookiecutter value is bound to a short module constant below and
referenced through it, and every import line is short enough that a long package name cannot
push it past the formatter's limit.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hex_service_kit.audit import HashChainedAuditLog
from hex_service_kit.identity import RequestContext
from hex_service_kit.serialization import to_jsonable

from contract_obligation_extraction.config import (
    Settings,
    build_container,
)
from contract_obligation_extraction.domain import (
    kernel,
    models,
)
from contract_obligation_extraction.domain.corpus import (
    AS_OF,
    contract_by_id,
)
from contract_obligation_extraction.domain.pii import (
    JURISDICTIONS,
)
from contract_obligation_extraction.domain.triage_service import (
    TriageService,
)
from contract_obligation_extraction.flow import (
    run_contract_register,
)


def loaded_cloud_sdks() -> tuple[str, ...]:
    """Every managed-SDK module currently importable in THIS interpreter, sorted.

    Public because the demo, the walkthrough's checks and the test suite all ask the same
    question and must not each answer it slightly differently.
    """
    return tuple(sorted(name for name in sys.modules if name.split(".")[0] == "google"))


#: Rendered identity, bound once so no other line's length depends on how long a name is.
SERVICE_NAME = "Contract Obligation Extraction"
CATALOG_ID = "Rgc12"
REPOSITORY = "contract-obligation-extraction"

# --------------------------------------------------------------------------------------- #
# Synthetic data. Fictional parties, .example domains, RFC 5737 / RFC 3849 literals only.
# --------------------------------------------------------------------------------------- #

#: The VERIFIED principal the demo attributes work to. A client never asserts this.
ACTOR = "analyst@bank.example"
TENANT = "demo-bank"

#: A planted identifier, so the redaction panel has an independent literal to look for rather
#: than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

ROUTINE_CASE = models.TriageInput(
    subject="Beta Trading (FICTIONAL)",
    text="routine note about a stationery order raised from 192.0.2.10",
)

ESCALATING_CASE = models.TriageInput(
    subject="Acme Holdings (FICTIONAL)",
    text="urgent data breach reported by the branch this morning",
)

PII_CASE = models.TriageInput(
    subject="Gamma LLP (FICTIONAL)",
    text=(
        "urgent breach: NRIC "
        + PLANTED_NRIC
        + " and mail ops@gamma.example seen on host 2001:db8::7"
    ),
)


# --------------------------------------------------------------------------------------- #
# The presenter arc
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Step:
    """One presenter beat: what it shows, and the sentence the presenter reads aloud."""

    key: str
    label: str
    narration: str


#: The scripted arc, in order. ``walkthrough.py`` asserts the server reaches each key in turn
#: and carries an expectation per key, so a step added here without an expectation there fails
#: the self-test rather than silently extending the demo.
STEPS: tuple[Step, ...] = (
    Step(
        key="opened",
        label="Service bound on the offline profile",
        narration=(
            "The whole stack is bound from one settings file: no cloud project, no credentials, "
            "no SDK. Every port has an offline implementation, which is why this demo and the "
            "gate both run on a plane."
        ),
    ),
    Step(
        key="routine",
        label="A routine case: decided, cited, NOT escalated",
        narration=(
            "A low-severity case. The band comes from deterministic code, never from a model. "
            "Nothing is routed for review, because manufacturing a review for a routine case "
            "trains reviewers to rubber-stamp."
        ),
    ),
    Step(
        key="escalation",
        label="A consequential case: escalated AND routed (rule R8)",
        narration=(
            "A high-severity case. Setting the flag is not the escalation; routing is. The "
            "result is handed to the human-review console in the same call that produced it, "
            "and the reference records where it went."
        ),
    ),
    Step(
        key="register",
        label="A contract read into its obligation register (the vertical)",
        narration=(
            "The model PROPOSES obligations, dates and risk flags; the deterministic engine "
            "OWNS admission. A candidate citing a clause that does not exist is dropped, flags "
            "are validated against the taxonomy, and an overdue renewal notice is a fact the "
            "clock computes. The material register routes to a human, and it carries a versioned "
            "feed for the downstream vendor-risk system."
        ),
    ),
    Step(
        key="redaction",
        label="Personal data is masked BEFORE the audit write",
        narration=(
            "The same path, with a national id planted in the case text. The identifier is "
            "masked before anything is written, so the immutable record never contains it. "
            "Redacting afterwards would be too late: the record is already immutable."
        ),
    ),
    Step(
        key="review_queue",
        label="What the reviewer receives, already redacted on the wire",
        narration=(
            "The outbound review queue. The console is a SHARED sink, so payloads are redacted "
            "against every configured jurisdiction, not only the one this case came from."
        ),
    ),
    Step(
        key="audit",
        label="The audit trail verifies, and exports in an open format",
        narration=(
            "The trail is append-only and hash-chained, with an external head anchor on a "
            "separate volume. It exports to JSON Lines and reloads into a fresh store with "
            "every link intact: the record is yours, not this codebase's."
        ),
    ),
    Step(
        key="tamper",
        label="A rewritten record is DETECTED, not merely discouraged",
        narration=(
            "An attacker with file access drops the append-only triggers and rewrites one "
            "record. The store cannot prevent that. The hash chain names the exact record that "
            "broke, which is the honest guarantee: tamper-EVIDENT, not tamper-proof."
        ),
    ),
    Step(
        key="portability",
        label="The exit path fails fast instead of failing silently",
        narration=(
            "The same calls on the on-premises profile, with no code edited and no domain "
            "module touched. Every unimplemented seam refuses loudly. A placeholder that "
            "returned successfully would convert an escalation into an unreviewed decision."
        ),
    ),
)

STEP_KEYS: tuple[str, ...] = tuple(step.key for step in STEPS)


# --------------------------------------------------------------------------------------- #
# Panels: the audit-first output view (the result, its evidence, the findings, what is next)
# --------------------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Row:
    """One labelled fact in a panel. ``tone`` drives the colour, never the meaning."""

    label: str
    value: str
    tone: str = ""


@dataclass(frozen=True, slots=True)
class Panel:
    """One block of the output view: a title, labelled facts, and an interpretation."""

    title: str
    rows: tuple[Row, ...] = ()
    note: str = ""
    tone: str = ""


@dataclass(frozen=True, slots=True)
class StepResult:
    """Everything one step produced, ready to render or to assert against."""

    key: str
    label: str
    narration: str
    panels: tuple[Panel, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)


Produced = tuple[list[Panel], dict[str, Any]]


class DemoRun:
    """A live demo, advanced one step at a time over the real services.

    The run owns a working directory holding the durable audit store and its external anchor.
    They are separate directories on purpose: an anchor that lives beside the store it witnesses
    is rewritten by whatever rewrites the store.
    """

    def __init__(self, workdir: Path | None = None) -> None:
        # What was ALREADY loaded before this run began. The offline claim is that the demo
        # imports no cloud SDK, and in a live `python scripts/demo.py` nothing else has loaded
        # one, so the delta and the absolute set are the same list. In a shared pytest process
        # they are not: any other module in the suite may legitimately have imported google for
        # its own reasons (the IAP negative matrix does), and a claim measured as an absolute
        # would then be decided by test ordering rather than by the demo. The absolute form of
        # the claim is still made, in fresh interpreters, by `scripts/portability_demo.py`, by
        # the headless walkthrough and by `tests/unit/test_demo_surface.py`.
        self._cloud_sdk_before = frozenset(loaded_cloud_sdks())
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        if workdir is None:
            self._tempdir = tempfile.TemporaryDirectory(prefix="demo-run-")
            workdir = Path(self._tempdir.name)
        self.workdir = workdir
        self.audit_path = workdir / "store" / "audit.sqlite3"
        self.anchor_path = workdir / "anchor" / "head.json"
        # The audit store creates its own parent; the ANCHOR does not, because it is meant to
        # live on a volume somebody provisioned deliberately rather than one a library invented.
        # An operator therefore has to create that directory too; the demo does it here so the
        # first run of `make demo` in a fresh checkout does not fail on a missing path.
        self.anchor_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(
            profile="local",
            audit_path=str(self.audit_path),
            audit_anchor_path=str(self.anchor_path),
            tenant=TENANT,
        )
        self.container = build_container(self.settings)
        self.service = TriageService(self.container.audit, self.container.tracer)
        self.results: list[StepResult] = []
        self.cases = 0
        self.escalated = 0
        self.routed = 0
        self.chain_ok = True
        self._perform(STEPS[0])

    # -------------------------------------------------------------- control

    @property
    def index(self) -> int:
        """Index of the step most recently performed."""
        return len(self.results) - 1

    @property
    def done(self) -> bool:
        return len(self.results) >= len(STEPS)

    def advance(self) -> StepResult:
        """Perform the next step, or re-return the last one when the arc is finished."""
        if self.done:
            return self.results[-1]
        return self._perform(STEPS[len(self.results)])

    def run_to_end(self) -> None:
        while not self.done:
            self.advance()

    def _perform(self, step: Step) -> StepResult:
        handler: Callable[[], Produced] = getattr(self, "_step_" + step.key)
        panels, facts = handler()
        result = StepResult(
            key=step.key,
            label=step.label,
            narration=step.narration,
            panels=tuple(panels),
            facts=facts,
        )
        self.results.append(result)
        return result

    # -------------------------------------------------------------- steps

    def _step_opened(self) -> Produced:
        bindings = [
            Row(port, self.settings.adapters[port][self.settings.profile].split(":")[-1])
            for port in sorted(self.settings.adapters)
        ]
        profiles = sorted({name for table in self.settings.adapters.values() for name in table})
        sdk = [name for name in loaded_cloud_sdks() if name not in self._cloud_sdk_before]
        deployment = Panel(
            title="Deployment",
            rows=(
                Row("Service", SERVICE_NAME),
                Row("Catalog id", CATALOG_ID),
                Row("Profile", self.settings.profile, "ok"),
                Row("Profiles bound for every port", ", ".join(profiles)),
                Row("Residency region", self.settings.region),
                Row("Jurisdiction PII packs", ", ".join(JURISDICTIONS)),
            ),
            note=(
                "One environment variable selects the adapter family for every port. Nothing "
                "below was edited to make the service run offline."
            ),
        )
        adapters = Panel(
            title="Bound adapters",
            rows=tuple(bindings),
            note="The binding map lives in config/settings.yaml, not in the code.",
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Cloud SDK modules imported", ", ".join(sdk) or "none", "bad" if sdk else "ok"),
                Row("Credentials required", "none", "ok"),
                Row("Network required", "none", "ok"),
            ),
            note=(
                "The managed adapters import their SDK lazily, so this profile runs with none "
                "installed at all."
            ),
            tone="bad" if sdk else "ok",
        )
        facts = {"profile": self.settings.profile, "sdk_modules": sdk, "profiles": profiles}
        return [deployment, adapters, findings], facts

    def _step_routine(self) -> Produced:
        return self._triage_panels(ROUTINE_CASE, expect_routing=False)

    def _step_escalation(self) -> Produced:
        return self._triage_panels(ESCALATING_CASE, expect_routing=True)

    def _step_register(self) -> Produced:
        # The consequential contract: an overdue renewal notice, material flags, and a candidate
        # that cites a clause the contract does not contain. Plus the MSA, to show the dropped
        # uncited candidate on a second family.
        outsourcing = contract_by_id("apex-outsourcing-2026")
        msa = contract_by_id("meridian-msa-2026")
        assert outsourcing is not None and msa is not None
        outcome = run_contract_register(
            self.container, outsourcing, as_of=AS_OF, actor=ACTOR, tenant=TENANT
        )
        msa_outcome = run_contract_register(
            self.container, msa, as_of=AS_OF, actor=ACTOR, tenant=TENANT
        )
        reg = outcome.register
        if outcome.review_ref:
            self.escalated += 1
            self.routed += 1
        if msa_outcome.review_ref:
            self.escalated += 1
            self.routed += 1

        counts = dict(reg.counts)
        overdue = counts.get("overdue", 0)
        obligations = Panel(
            title="Register: " + reg.counterparty,
            rows=tuple(
                Row(
                    row.clause_anchor.split("#")[-1],
                    (", ".join(row.flag_values) or "no flag")
                    + (" [needs review]" if row.needs_review else ""),
                    "bad" if row.needs_review else "ok",
                )
                for row in reg.obligations
            ),
            note=(
                "Each row links to its source clause. Flags are validated against the taxonomy; "
                "an unknown flag would be dropped, not coerced to the nearest known one."
            ),
        )
        deadline = Panel(
            title="Renewal clock",
            rows=tuple(
                Row(
                    row.clause_anchor.split("#")[-1],
                    _deadline_label(row),
                    "bad" if (row.deadline and row.deadline.breached) else "ok",
                )
                for row in reg.obligations
                if row.deadline is not None
            )
            or (Row("deadlines", "none in this contract"),),
            note=(
                "An overdue renewal notice can auto-renew a contract a firm meant to exit, so it "
                "is consequential: the clock computes it and it routes for review."
            ),
            tone="bad" if overdue else "ok",
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Obligations admitted", str(counts.get("obligations", 0))),
                Row("Flagged", str(counts.get("flagged", 0))),
                Row("Needs review", str(counts.get("needs_review", 0))),
                Row("Overdue deadlines", str(overdue), "bad" if overdue else "ok"),
                Row(
                    "Uncited candidates dropped (MSA)",
                    str(len(msa_outcome.register.dropped)),
                    "ok" if msa_outcome.register.dropped else "bad",
                ),
                Row("Severity", reg.severity.value, "bad"),
                Row(
                    "Routed to review (R8)",
                    outcome.review_ref or "NOT ROUTED",
                    "ok" if outcome.review_ref else "bad",
                ),
                Row("Feed schema version", str(reg.snapshot.version) + " / kit-versioned"),
                Row("Narration model-authored", str(outcome.note.model_authored)),
            ),
            note=(
                "The numbers are the engine's; the note only restates them. With the model "
                "stubbed the numbers are byte-identical, which is what makes the result safe."
            ),
            tone="bad" if overdue else "ok",
        )
        summary = Panel(
            title="Grounded summary",
            rows=(Row("Register", outcome.note.text),),
            note="Every figure in the summary comes from the engine, never the model.",
        )
        facts = {
            "obligations": counts.get("obligations", 0),
            "flagged": counts.get("flagged", 0),
            "overdue": overdue,
            "dropped_msa": len(msa_outcome.register.dropped),
            "review_ref": outcome.review_ref,
            "feed_version": reg.snapshot.version,
            "severity": reg.severity.value,
            "note_grounded": outcome.note.grounded,
        }
        return [obligations, deadline, findings, summary], facts

    def _step_redaction(self) -> Produced:
        panels, facts = self._triage_panels(PII_CASE, expect_routing=True)
        recorded = str(self.container.audit.log.read_all()[-1]["redacted_summary"])
        leaked = PLANTED_NRIC in recorded
        panels.append(
            Panel(
                title="Redact before the write",
                rows=(
                    Row("Identifier in the submitted text", PLANTED_NRIC, "warn"),
                    Row(
                        "Identifier in the immutable record",
                        "PRESENT" if leaked else "absent",
                        "bad" if leaked else "ok",
                    ),
                    Row("Stored summary", recorded),
                ),
                note=(
                    "The record is immutable, so a redaction pass after the write would be too "
                    "late. Masking happens on the way in."
                ),
                tone="bad" if leaked else "ok",
            )
        )
        facts["planted_identifier_leaked"] = leaked
        return panels, facts

    def _step_review_queue(self) -> Produced:
        pending = list(self.container.review_router.outbox.pending())
        rows: list[Row] = []
        leaked = False
        for item in pending:
            payload = to_jsonable(item)
            leaked = leaked or PLANTED_NRIC in json.dumps(payload, sort_keys=True)
            rows.append(Row(str(getattr(item, "source_key", "review")), _summarise(payload)))
        queue = Panel(
            title="Outbound review queue",
            rows=tuple(rows) or (Row("queue", "empty", "bad"),),
            note=(
                "Queued, not submitted. The reference the caller received says exactly that, so "
                "a buffered escalation is never mistaken for a reviewed one."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Escalated results", str(self.escalated)),
                Row(
                    "Routed to review",
                    str(self.routed),
                    "ok" if self.routed == self.escalated else "bad",
                ),
                Row(
                    "Personal data on the wire",
                    "LEAKED" if leaked else "none",
                    "bad" if leaked else "ok",
                ),
            ),
            note=(
                "Every escalation is accounted for. A flag with no routing reference is "
                "auto-execution with extra steps."
            ),
            tone="bad" if leaked or self.routed != self.escalated else "ok",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Reviewer", "open the queued item and approve or reject it"),
                Row("Operator", "point HUMAN_REVIEW_URL at the console and flush the outbox"),
            ),
        )
        return [queue, findings, actions], {"pending": len(pending), "wire_leak": leaked}

    def _step_audit(self) -> Produced:
        log = self.container.audit.log
        report = self.container.audit.verify()
        self.chain_ok = report.ok
        export = self.workdir / "export" / "audit.jsonl"
        export.parent.mkdir(parents=True, exist_ok=True)
        written = log.export_jsonl(export)
        restored = HashChainedAuditLog(":memory:")
        reloaded = restored.import_jsonl(export)
        round_trip = restored.verify_chain()
        anchored = bool(self.settings.audit_anchor_path) and self.anchor_path.exists()
        trail = Panel(
            title="Audit trail",
            rows=(
                Row("Records", str(report.entries)),
                Row("Hash-chained", str(report.chained)),
                Row(
                    "Unverifiable (unchained)",
                    str(report.legacy),
                    "ok" if report.legacy == 0 else "bad",
                ),
                Row("Verdict", report.detail, "ok" if report.ok else "bad"),
                Row(
                    "External head anchor",
                    "configured" if anchored else "absent",
                    "ok" if anchored else "warn",
                ),
            ),
            note=(
                "The chain alone cannot detect a truncated tail: dropping the newest rows leaves "
                "a shorter chain that verifies perfectly. The anchor, kept on a different "
                "volume, is what closes that gap."
            ),
            tone="ok" if report.ok else "bad",
        )
        portable = Panel(
            title="Open-format round trip",
            rows=(
                Row("Exported records", str(written)),
                Row("Reloaded into a fresh store", str(reloaded)),
                Row(
                    "Chain after reload",
                    round_trip.detail,
                    "ok" if round_trip.ok else "bad",
                ),
            ),
            note=(
                "JSON Lines with the hashes included, so a consumer can re-verify the trail "
                "without this codebase. That is what makes the record portable."
            ),
            tone="ok" if round_trip.ok else "bad",
        )
        facts = {
            "chain_ok": report.ok,
            "entries": report.entries,
            "exported": written,
            "round_trip_ok": round_trip.ok,
            "anchored": anchored,
        }
        return [trail, portable], facts

    def _step_tamper(self) -> Produced:
        before = self.container.audit.verify()
        target = _rewrite_a_record(self.audit_path)
        after = self.container.audit.verify()
        self.chain_ok = after.ok
        detected = (not after.ok) and after.first_bad_seq == target
        attack = Panel(
            title="The tamper",
            rows=(
                Row("Append-only triggers", "dropped by the attacker", "warn"),
                Row("Record rewritten in place", "seq " + str(target), "warn"),
                Row("Verdict before the rewrite", before.detail, "ok"),
            ),
            note=(
                "File access beats a database trigger. A store that claims otherwise is "
                "describing a policy, not a control."
            ),
        )
        findings = Panel(
            title="Findings",
            rows=(
                Row("Chain intact", "YES" if after.ok else "no", "bad" if after.ok else "ok"),
                Row("First broken record", str(after.first_bad_seq), "ok"),
                Row("Detail", after.detail),
                Row(
                    "Named the exact rewritten record",
                    "yes" if detected else "no",
                    "ok" if detected else "bad",
                ),
            ),
            note=(
                "Tamper-EVIDENT, not tamper-proof. The guarantee is that a rewrite cannot pass "
                "unnoticed, and that the report names which record broke."
            ),
            tone="ok" if detected else "bad",
        )
        actions = Panel(
            title="Next actions",
            rows=(
                Row("Operator", "restore from the exported JSONL and re-anchor deliberately"),
                Row("Auditor", "treat every record from seq " + str(target) + " on as suspect"),
            ),
        )
        facts = {"tampered_seq": target, "detected": detected, "chain_ok": after.ok}
        return [attack, findings, actions], facts

    def _step_portability(self) -> Produced:
        onprem = build_container(Settings(profile="onprem", tenant=TENANT))
        rows: list[Row] = []
        refused: list[str] = []
        absent: list[str] = []
        for port, call in EXIT_CALLS.items():
            expected_absent = port in EXIT_ABSENT
            try:
                call(onprem)
            except NotImplementedError as exc:
                if expected_absent:
                    rows.append(Row(port, "REFUSED, but is meant to be absent", "bad"))
                else:
                    refused.append(port)
                    rows.append(Row(port, "refused: " + str(exc).split(":")[0], "ok"))
            else:
                if expected_absent:
                    absent.append(port)
                    rows.append(Row(port, "absent, by design (a diagnostic, not a control)", "ok"))
                else:
                    rows.append(Row(port, "SUCCEEDED SILENTLY", "bad"))
        exit_panel = Panel(
            title="Exit profile (onprem)",
            rows=tuple(rows),
            note=(
                "Selected by one environment variable. No domain module was edited and no "
                "import changed."
            ),
            tone="ok" if len(refused) + len(absent) == len(EXIT_CALLS) else "bad",
        )
        bounds = Panel(
            title="What this does and does not prove",
            rows=(
                Row("Proved", "every port is swappable and every seam is named"),
                Row("Proved", "an unimplemented seam refuses instead of dropping work"),
                Row("NOT proved", "a running on-premises deployment exists"),
                Row("NOT proved", "model, infrastructure or whole-system portability"),
            ),
            note=(
                "Bounded claims are the point. Run scripts/portability_demo.py for the full "
                "seam tour, with a pass or fail per named check."
            ),
        )
        return [exit_panel, bounds], {
            "refused": sorted(refused),
            "absent": sorted(absent),
        }

    # -------------------------------------------------------------- helpers

    def _triage_panels(self, case: models.TriageInput, *, expect_routing: bool) -> Produced:
        result = self.service.triage(case, actor=ACTOR)
        self.cases += 1
        review_ref = ""
        if result.requires_human_review:
            self.escalated += 1
            review_ref = self.container.review_router.route(result, maker=ACTOR, tenant=TENANT)
            self.routed += 1
        consistent = bool(review_ref) == expect_routing == result.requires_human_review
        decision = Panel(
            title="Decision: " + result.subject,
            rows=(
                Row(
                    "Severity",
                    result.severity.value,
                    "bad" if result.requires_human_review else "ok",
                ),
                Row("Decision", result.decision.value),
                Row("Requires human review", str(result.requires_human_review)),
                Row(
                    "Routed to review",
                    review_ref or "not routed (routine)",
                    "ok" if consistent else "bad",
                ),
                Row("Attributed to", ACTOR),
            ),
            note=(
                "The band is computed by pure stdlib code and is replayable. A model would "
                "narrate this result; it never produces it."
            ),
            tone="ok" if consistent else "bad",
        )
        evidence = Panel(
            title="Evidence",
            rows=tuple(
                Row(citation.title, citation.snippet or citation.source_id)
                for citation in result.citations
            )
            or (Row("citations", "NONE", "bad"),),
            note="Every claim carries its source. An uncited claim is a hallucination risk.",
        )
        facts = {
            "subject": result.subject,
            "severity": result.severity.value,
            "requires_human_review": result.requires_human_review,
            "review_ref": review_ref,
            "consistent": consistent,
        }
        return [decision, evidence], facts

    # -------------------------------------------------------------- state

    def state(self) -> dict[str, Any]:
        """The whole run as JSON-safe data: what the UI renders and the walkthrough asserts."""
        current = self.results[-1]
        return {
            "service": SERVICE_NAME,
            "catalog_id": CATALOG_ID,
            "repository": REPOSITORY,
            "profile": self.settings.profile,
            "region": self.settings.region,
            "step": current.key,
            "step_index": self.index,
            "step_count": len(STEPS),
            "label": current.label,
            "next": "" if self.done else STEPS[len(self.results)].label,
            "done": self.done,
            "totals": {
                "cases": self.cases,
                "escalated": self.escalated,
                "routed": self.routed,
                "chain_ok": self.chain_ok,
            },
            "steps": [_step_to_dict(result) for result in self.results],
        }


def _step_to_dict(result: StepResult) -> dict[str, Any]:
    return {
        "key": result.key,
        "label": result.label,
        "narration": result.narration,
        "facts": result.facts,
        "panels": [
            {
                "title": panel.title,
                "note": panel.note,
                "tone": panel.tone,
                "rows": [
                    {"label": row.label, "value": row.value, "tone": row.tone} for row in panel.rows
                ],
            }
            for panel in result.panels
        ],
    }


def _deadline_label(row: Any) -> str:
    """A readable one-line status for an obligation's deadline in the register panel."""
    dv = row.deadline
    if dv is None:
        return "no deadline"
    if dv.breached:
        return f"OVERDUE by {abs(dv.days_until)}d ({dv.kind})"
    if dv.in_notice_window:
        return f"in notice window, due {dv.due_on.isoformat()} ({dv.kind})"
    return f"due {dv.due_on.isoformat()} in {dv.days_until}d ({dv.kind})"


def _summarise(payload: Any) -> str:
    """One readable line for a queued review, without dumping the whole payload."""
    if isinstance(payload, dict):
        parts = [
            str(payload[key])
            for key in ("title", "severity", "maker", "tenant")
            if payload.get(key)
        ]
        if parts:
            return " / ".join(parts)
    return json.dumps(payload, sort_keys=True)[:120]


def _rewrite_a_record(store: Path) -> int:
    """Drop the append-only triggers and rewrite one INTERIOR record, as an attacker would.

    Returns the ``seq`` that was rewritten. An interior row is chosen deliberately: rewriting
    the newest row is the easy case, and the chain has to catch a rewrite in the middle of the
    trail too.
    """
    conn = sqlite3.connect(store)
    try:
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
        conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
        rows = conn.execute("SELECT seq, event_json FROM audit_log ORDER BY seq ASC").fetchall()
        if len(rows) < 3:
            raise RuntimeError("the tamper step needs an interior record to rewrite")
        middle = rows[len(rows) // 2]
        payload = json.loads(middle[1])
        payload["decision"] = "allowed"
        payload["severity"] = "low"
        conn.execute(
            "UPDATE audit_log SET event_json = ? WHERE seq = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), int(middle[0])),
        )
        conn.commit()
        return int(middle[0])
    finally:
        conn.close()


def _exit_audit(container: Any) -> Any:
    return container.audit.record(
        kernel.AuditEvent(
            action="triage",
            actor=ACTOR,
            decision=kernel.Decision.ESCALATED,
            severity=kernel.Severity.HIGH,
            redacted_summary="Acme Holdings (FICTIONAL): triaged high",
        )
    )


def _exit_review(container: Any) -> Any:
    citation = kernel.Citation(
        source_id="case:acme",
        title="Case description",
        snippet="urgent",
    )
    return container.review_router.route(
        models.TriageResult(
            subject=ESCALATING_CASE.subject,
            severity=kernel.Severity.HIGH,
            decision=kernel.Decision.ESCALATED,
            summary="Acme Holdings (FICTIONAL): triaged high",
            requires_human_review=True,
            citations=(citation,),
        ),
        maker=ACTOR,
        tenant=TENANT,
    )


def _exit_identity(container: Any) -> Any:
    # The persona header is deliberately present. It is what the OFFLINE family answers, so
    # sending it proves the exit family refuses the call itself rather than merely lacking an
    # input: a placeholder that returned a principal for a client-written header would be worse
    # than one that raises.
    return container.identity.resolve(RequestContext(headers={"x-dev-persona": "approver"}))


def _exit_generation(container: Any) -> Any:
    from contract_obligation_extraction.ports.generation import GenerationRequest

    return container.generation.generate(
        GenerationRequest(system="restate", prompt="Facts:\nobligations=1\n")
    )


def _exit_extraction(container: Any) -> Any:
    from contract_obligation_extraction.ports.extraction import ExtractionRequest

    return container.extraction.extract(
        ExtractionRequest(
            contract_id="meridian-msa-2026",
            family="msa",
            counterparty="Meridian Cloud Services Pte Ltd (FICTIONAL)",
            clauses=(),
        )
    )


def _exit_tracer(container: Any) -> Any:
    with container.tracer.span("exit.tour", action="portability"):
        return None


def _exit_evaluation(container: Any) -> Any:
    return container.evaluation.gate("eval/datasets/golden_cases.jsonl")


#: The calls the exit profile must REFUSE, one per port with an exit placeholder. Add a port,
#: add a row: a seam nobody calls is a seam nobody knows is unimplemented.
#:
#: IDENTITY is the load-bearing one and it was the one missing. What the bound identity adapter
#: DECLARES is the single flag the exposure guard reads before it stands down and lets the
#: process bind every interface, so a portability tour that toured every seam except that one
#: was skipping the seam whose exit behaviour matters most.
EXIT_CALLS: dict[str, Callable[[Any], Any]] = {
    "audit": _exit_audit,
    "identity": _exit_identity,
    "review_router": _exit_review,
    "tracer": _exit_tracer,
    "evaluation": _exit_evaluation,
    "generation": _exit_generation,
    "extraction": _exit_extraction,
}


#: Diagnostic seams that complete as an honest no-op under the exit profile.
EXIT_ABSENT: frozenset[str] = frozenset({"tracer"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scripted offline demo end to end.")
    parser.add_argument(
        "output",
        nargs="?",
        default="demo.json",
        help="where to write the audit-view JSON (default: demo.json)",
    )
    parser.add_argument("--quiet", action="store_true", help="write the JSON and print nothing")
    args = parser.parse_args(argv)

    run = DemoRun()
    run.run_to_end()
    state = run.state()
    Path(args.output).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        for step in state["steps"]:
            print("[" + step["key"] + "] " + step["label"])
        totals = state["totals"]
        print(
            "cases="
            + str(totals["cases"])
            + " escalated="
            + str(totals["escalated"])
            + " routed="
            + str(totals["routed"])
        )
        print("wrote " + args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
