"""The executable portability claim (practices check F3): named checks, pass or fail, exit code.

A portability claim written in a README is a sentence. This is the same claim as a program: it
runs every port through every profile, proves the offline family answers and the exit family
refuses, proves the audit record survives leaving this codebase, and exits non-zero the moment
one of those stops being true.

WHAT IT PROVES

* every declared port has a binding in every profile, in all of the places a binding lives;
* every adapter constructs from one ``Settings`` and satisfies its Protocol;
* the offline family ANSWERS a canonical call (not merely "did not raise");
* the exit family REFUSES loudly rather than dropping the work;
* the audit trail is tamper-evident, and an anchored trail also detects a truncated tail;
* the trail exports to an open format and reloads into a foreign store with its chain intact;
* none of the above imports a cloud SDK.

WHAT IT DOES NOT PROVE

* that an on-premises deployment exists, or that anyone has run one;
* infrastructure, model, network or whole-system portability;
* anything at all about the managed profile's live behaviour, which needs a cloud project and
  lives in ``tests/integration/``.

Bounding the claim is the point. An unbounded claim is the one an auditor disproves for you.

    make portability
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import demo
from hex_service_kit.audit import EXPORT_FORMAT, AuditChainError, HashChainedAuditLog

from contract_obligation_extraction import (
    config,
)
from contract_obligation_extraction.domain import (
    kernel,
)
from contract_obligation_extraction.ports import (
    PORT_PROTOCOLS,
)

OFFLINE = "local"
EXIT_PROFILE = "onprem"


@dataclass(frozen=True, slots=True)
class Check:
    """One named claim and the callable that either substantiates it or explains itself."""

    name: str
    run: Callable[[], str]


def _settings(profile: str, **overrides: Any) -> config.Settings:
    base: dict[str, Any] = {"profile": profile, "tenant": demo.TENANT}
    base.update(overrides)
    return config.Settings(**base)


def check_every_port_is_bound_in_every_profile() -> str:
    settings = _settings(OFFLINE)
    declared = set(PORT_PROTOCOLS)
    bound = set(settings.adapters)
    if declared != bound:
        raise AssertionError(
            "declared ports " + str(sorted(declared)) + " != bound " + str(sorted(bound))
        )
    profiles = config.KNOWN_PROFILES
    for port, table in settings.adapters.items():
        missing = set(profiles) - set(table)
        if missing:
            raise AssertionError(port + " has no binding for " + ", ".join(sorted(missing)))
    return str(len(declared)) + " ports x " + str(len(profiles)) + " profiles, all bound"


def check_every_adapter_constructs_and_conforms() -> str:
    built = 0
    for profile in config.KNOWN_PROFILES:
        container = config.build_container(_settings(profile))
        for port, protocol in PORT_PROTOCOLS.items():
            adapter = getattr(container, port)
            if not isinstance(adapter, protocol):
                raise AssertionError(profile + "/" + port + " does not satisfy its Protocol")
            built += 1
    return str(built) + " adapters constructed from one Settings each"


def check_the_offline_family_answers() -> str:
    container = config.build_container(_settings(OFFLINE))
    container.audit.record(_event())
    stored = container.audit.log.read_all()
    if not stored or stored[-1]["actor"] != demo.ACTOR:
        raise AssertionError("the offline audit sink did not store the record")
    # Through the SAME call table the exit check drives, so the two sides of the claim cannot
    # drift: a seam the offline family answers by one route and the exit family refuses by
    # another has not been shown to be one seam.
    principal = demo.EXIT_CALLS["identity"](container)
    if not principal.actor:
        raise AssertionError("the offline identity adapter resolved no actor")
    reference = demo.EXIT_CALLS["review_router"](container)
    if not reference:
        raise AssertionError("the offline review router returned no routing reference")
    return "audit stored, principal resolved, review routed (" + str(reference) + ")"


def check_the_exit_family_refuses() -> str:
    # EVERY declared port needs a call here, or the tour reports a green refusal for the seams
    # somebody remembered and says nothing about the rest. The identity seam was missing exactly
    # this way, and it is the one whose declaration decides whether the service may be reached
    # from anywhere but loopback at all.
    untoured = sorted(set(PORT_PROTOCOLS) - set(demo.EXIT_CALLS))
    if untoured:
        raise AssertionError(
            "no exit call for " + ", ".join(untoured) + "; add one to demo.EXIT_CALLS"
        )
    container = config.build_container(_settings(EXIT_PROFILE))
    refused: list[str] = []
    absent: list[str] = []
    for port, call in demo.EXIT_CALLS.items():
        expected_absent = port in demo.EXIT_ABSENT
        try:
            call(container)
        except NotImplementedError:
            if expected_absent:
                raise AssertionError(
                    port + " REFUSED on the exit profile but is documented as absent by design"
                ) from None
            refused.append(port)
        else:
            if not expected_absent:
                raise AssertionError(port + " SUCCEEDED on the exit profile instead of refusing")
            absent.append(port)
    return (
        "refused loudly: "
        + ", ".join(sorted(refused))
        + "; absent by design: "
        + ", ".join(sorted(absent))
    )


def check_a_rewritten_record_is_detected() -> str:
    with tempfile.TemporaryDirectory(prefix="portability-") as work:
        store = Path(work) / "audit.sqlite3"
        log = HashChainedAuditLog(str(store))
        for _ in range(3):
            log.record(_event())
        if not log.verify_chain().ok:
            raise AssertionError("a freshly written chain did not verify")
        seq = _rewrite_interior(store)
        report = log.verify_chain()
        if report.ok or report.first_bad_seq != seq:
            raise AssertionError("the rewritten record was not detected at seq " + str(seq))
    return "in-place rewrite detected at seq " + str(seq)


def check_an_anchored_trail_detects_truncation() -> str:
    with tempfile.TemporaryDirectory(prefix="portability-") as work:
        store = Path(work) / "store" / "audit.sqlite3"
        anchor = Path(work) / "anchor" / "head.json"
        # The store creates its own parent; the anchor does not, because it belongs on a volume
        # an operator provisioned rather than one a library invented. Provision it here.
        anchor.parent.mkdir(parents=True, exist_ok=True)
        log = HashChainedAuditLog(str(store), anchor_path=str(anchor))
        for _ in range(3):
            log.record(_event())
        _truncate_tail(store)
        anchored = HashChainedAuditLog(str(store), anchor_path=str(anchor)).verify_chain()
        if anchored.ok:
            raise AssertionError("an anchored trail did not notice a truncated tail")
        # The control case: without the anchor the SAME truncation verifies perfectly. It is
        # here so that quietly dropping the anchor wiring cannot leave this check still green.
        unanchored = HashChainedAuditLog(str(store)).verify_chain()
        if not unanchored.ok:
            raise AssertionError("the control case is wrong: an unanchored truncation was caught")
        try:
            HashChainedAuditLog(str(store), anchor_path=str(anchor)).record(_event())
        except AuditChainError:
            pass
        else:
            raise AssertionError("an append after truncation silently re-anchored the chain")
    return "truncation detected with the anchor, undetected without it, append refused"


def check_the_trail_leaves_this_codebase_intact() -> str:
    with tempfile.TemporaryDirectory(prefix="portability-") as work:
        source = HashChainedAuditLog(str(Path(work) / "audit.sqlite3"))
        for _ in range(3):
            source.record(_event())
        export = Path(work) / "audit.jsonl"
        written = source.export_jsonl(export)
        raw = export.read_text(encoding="utf-8").splitlines()
        lines = [json.loads(line) for line in raw]
        # The chain head travels with the trail: line 1 is the anchor header, and the record
        # lines follow it unchanged. So the file carries exactly one more LINE than the RECORD
        # count `export_jsonl` returns, and the head the records end on is stated in the file
        # rather than left behind with the store that wrote it.
        header, records = lines[0], lines[1:]
        if len(records) != written or header.get("format") != EXPORT_FORMAT:
            raise AssertionError("the export is not self-describing JSON Lines")
        if any("entry_hash" not in record for record in records):
            raise AssertionError("an exported record carries no chain hashes")
        if header["anchor"]["entry_hash"] != records[-1]["entry_hash"]:
            raise AssertionError("the export's anchor header does not commit to its own tail")
        foreign = HashChainedAuditLog(":memory:")
        reloaded = foreign.import_jsonl(export)
        if reloaded != written or not foreign.verify_chain().ok:
            raise AssertionError("the trail did not reload with its chain intact")
        # What the travelling anchor buys the RECIPIENT, and the reason the header is worth a
        # line: drop the newest record and the shorter chain still verifies link by link, so
        # the header is the only thing in the file that can expose the missing tail.
        truncated = Path(work) / "audit-truncated.jsonl"
        truncated.write_text("\n".join(raw[:-1]) + "\n", encoding="utf-8")
        try:
            HashChainedAuditLog(":memory:").import_jsonl(truncated)
        except AuditChainError:
            pass
        else:
            raise AssertionError("a truncated export reloaded without the anchor noticing")
    return str(written) + " records exported as JSONL and reloaded, chain intact"


def check_no_cloud_sdk_was_imported() -> str:
    loaded = sorted(name for name in sys.modules if name.split(".")[0] == "google")
    if loaded:
        raise AssertionError("a cloud SDK was imported by the offline path: " + str(loaded))
    return "no google.* module imported by any check above"


CHECKS: tuple[Check, ...] = (
    Check("port map complete", check_every_port_is_bound_in_every_profile),
    Check("adapters construct and conform", check_every_adapter_constructs_and_conforms),
    Check("offline family answers", check_the_offline_family_answers),
    Check("exit family refuses", check_the_exit_family_refuses),
    Check("rewrite detected", check_a_rewritten_record_is_detected),
    Check("truncation detected when anchored", check_an_anchored_trail_detects_truncation),
    Check("record leaves intact", check_the_trail_leaves_this_codebase_intact),
    Check("no cloud SDK imported", check_no_cloud_sdk_was_imported),
)


def _event() -> kernel.AuditEvent:
    return kernel.AuditEvent(
        action="triage",
        actor=demo.ACTOR,
        decision=kernel.Decision.ESCALATED,
        severity=kernel.Severity.HIGH,
        redacted_summary="Acme Holdings (FICTIONAL): triaged high",
    )


def _open_unguarded(store: Path) -> sqlite3.Connection:
    """Open the store with the append-only triggers dropped, the way file access would."""
    conn = sqlite3.connect(store)
    conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
    return conn


def _rewrite_interior(store: Path) -> int:
    conn = _open_unguarded(store)
    try:
        rows = conn.execute("SELECT seq, event_json FROM audit_log ORDER BY seq ASC").fetchall()
        middle = rows[len(rows) // 2]
        payload = json.loads(middle[1])
        payload["severity"] = "low"
        conn.execute(
            "UPDATE audit_log SET event_json = ? WHERE seq = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), int(middle[0])),
        )
        conn.commit()
        return int(middle[0])
    finally:
        conn.close()


def _truncate_tail(store: Path) -> None:
    conn = _open_unguarded(store)
    try:
        conn.execute("DELETE FROM audit_log WHERE seq = (SELECT MAX(seq) FROM audit_log)")
        conn.commit()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the portability seam tour and report.")
    parser.add_argument("--quiet", action="store_true", help="print only the verdict line")
    args = parser.parse_args(argv)

    failures = 0
    for check in CHECKS:
        try:
            detail = check.run()
        except Exception as exc:  # noqa: BLE001 - a check reports, it does not crash the tour
            failures += 1
            print("FAIL  " + check.name + ": " + str(exc))
            continue
        if not args.quiet:
            print("PASS  " + check.name + ": " + detail)

    print("")
    if failures:
        print("PORTABILITY: FAILED (" + str(failures) + " of " + str(len(CHECKS)) + ")")
        return 1
    print("PORTABILITY: PASS (" + str(len(CHECKS)) + " checks)")
    print("Bounded claim: offline seams and record portability only. See the module docstring.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
