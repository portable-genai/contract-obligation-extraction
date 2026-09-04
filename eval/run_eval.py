#!/usr/bin/env python3
"""Evaluation gate for Contract Obligation Extraction (contract-obligation-extraction).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change: it drives the real
  ``TriageService`` against a golden set with SDK-free local adapters and scores two metrics. *
  **gate** - the promotion verdict from the shared model-quality-gate authority (requires the
  ``gcp`` profile), via ``agent_eval_kit.PromotionGateClient``.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from agent_eval_kit import EvalMetricResult, EvalReport, PromotionGateClient, eval_main
from pii_kit import pack_leak

from contract_obligation_extraction.adapters.local.audit import (
    LocalAuditAdapter,
)
from contract_obligation_extraction.adapters.local.generation import (
    LocalGenerationAdapter,
)
from contract_obligation_extraction.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from contract_obligation_extraction.config import (
    Settings,
)
from contract_obligation_extraction.domain.contracts import (
    ContractObligation,
    RegisterService,
)
from contract_obligation_extraction.domain.corpus import (
    AS_OF,
    contract_by_id,
    proposals_for,
)
from contract_obligation_extraction.domain.models import (
    TriageInput,
)
from contract_obligation_extraction.domain.narration import (
    build_request,
    note_is_grounded,
    parse_note,
)
from contract_obligation_extraction.domain.pii import (
    PII_PATTERNS,
)
from contract_obligation_extraction.domain.triage_service import (
    TriageService,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"
#: The contract-extraction oracle: hand-computed clause linkages, flags and deadline status per
#: fictional contract. Scored by the engine (extraction/flag/deadline accuracy) and used to ground
#: the register narrator.
CONTRACT_DATASET = _REPO_ROOT / "eval" / "datasets" / "contract_oracle.jsonl"

THRESHOLDS: dict[str, float] = {
    "decision_accuracy": 0.80,
    "pii_safety": 0.99,
    "extraction_accuracy": 0.99,
    "flag_accuracy": 0.99,
    "deadline_accuracy": 0.99,
    "narration_groundedness": 0.99,
}
#: The registered model-quality-gate metric bundle for this vertical (model-quality-gate owns the
#: metrics + thresholds).
_BUNDLE = "contract-obligation-extraction"


def _load(path: Path) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _load_scenarios(path: Path) -> list[dict[str, object]]:
    """Load a jsonl oracle whose rows carry mixed types (ints, nested dicts), not just strings."""
    cases: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def audit_texts(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every CONTENT field of every audit row, as flat text for the leak scan.

    Scanning ``redacted_summary`` alone reads the one field the redactor is already masking: the
    metric asks the redactor whether it redacted and believes the answer, while the citation
    stored beside that summary carries the identifier verbatim into a record that is immutable
    and long-retained. A record is what the row HOLDS, so the scan reads the whole of it, and
    ``citations`` is serialised rather than walked field by field so a citation that grows a
    field is scanned the day it appears.

    ``action``, ``actor``, ``decision``, ``severity`` and ``timestamp`` are excluded. They are
    attribution and taxonomy, not content, and ``actor`` in particular is the verified principal
    and an address by design: a scan widened to whole rows could never be green, and the next fix
    would be to lower the threshold rather than to narrow the scan back.

    Module-level, and paired with :func:`pii_safety`, so ``tests/unit/test_not_falsely_green.py``
    falsifies the SHIPPED scan instead of a lookalike written above the assertion.
    """
    texts: list[str] = []
    for row in rows:
        texts.append(str(row.get("redacted_summary", "")))
        texts.append(json.dumps(row.get("citations", []), sort_keys=True))
    return texts


def pii_safety(records: Sequence[str], planted: Sequence[str]) -> float:
    """1.0 unless a raw identifier survives into any of ``records``; 0.0 the moment one does.

    Scored two independent ways because a single oracle can agree with itself. ``pack_leak`` uses
    the SAME rows the redactor masks with, so it catches a call site that never redacted; the
    planted-literal check knows nothing about the pack, so it still fires when a pattern row is
    broken or was never selected for this deployment's jurisdictions. Binary rather than a
    proportion: a leak in one record out of a hundred is a leak.
    """
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in records)
    literal_leaked = any(token in text for token in planted for text in records)
    return 0.0 if (pack_leaked or literal_leaked) else 1.0


def deadline_bucket(row: ContractObligation) -> str:
    """The deadline status bucket the oracle compares against (pure, engine-derived)."""
    dv = row.deadline
    if dv is None:
        return "none"
    if dv.breached:
        return "breached"
    if dv.in_notice_window:
        return "in_notice"
    return dv.status.value


def score_contracts(cases: list[dict[str, object]]) -> dict[str, float]:
    """Score the extraction engine and the register narrator against the independent oracle.

    Returns the four contract metrics. ``extraction_accuracy`` compares the admitted clause
    linkages and the dropped count to the hand-computed oracle; ``flag_accuracy`` and
    ``deadline_accuracy`` compare the validated flags and the deadline status per admitted
    obligation; ``narration_groundedness`` runs the RAW local narrator (never the already-filtered
    service output, which could not go red) and scores whether every figure in its note is one the
    engine produced. Any drift in segmentation, the taxonomy or the clock turns a metric red.
    """
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    service = RegisterService(audit)
    generation = LocalGenerationAdapter(Settings(profile="local"))

    extraction_scores: list[float] = []
    flag_scores: list[float] = []
    deadline_scores: list[float] = []
    grounded_scores: list[float] = []

    for case in cases:
        contract = contract_by_id(str(case["contract_id"]))
        if contract is None:
            raise SystemExit(f"oracle names unknown contract {case['contract_id']!r}")
        register = service.build(
            contract, proposals_for(contract.contract_id), as_of=AS_OF, actor="eval-bot"
        )
        rows = {row.clause_number: row for row in register.obligations}
        oracle_rows = dict(case["rows"])  # type: ignore[arg-type]

        linked = set(rows) == set(oracle_rows) and len(register.dropped) == int(
            str(case["expected_dropped"])
        )
        extraction_scores.append(1.0 if linked else 0.0)

        for number, expected in oracle_rows.items():
            row = rows.get(number)
            if row is None:
                flag_scores.append(0.0)
                deadline_scores.append(0.0)
                continue
            want_flags = sorted(str(f) for f in expected["flags"])  # type: ignore[index]
            flag_scores.append(1.0 if sorted(row.flag_values) == want_flags else 0.0)
            deadline_scores.append(
                1.0 if deadline_bucket(row) == str(expected["deadline"]) else 0.0  # type: ignore[index]
            )

        request = build_request(register)
        raw = generation.generate(request)
        note = parse_note(raw.text)
        grounded = note is not None and note_is_grounded(note, request.facts)
        grounded_scores.append(1.0 if grounded else 0.0)

    return {
        "extraction_accuracy": _mean(extraction_scores),
        "flag_accuracy": _mean(flag_scores),
        "deadline_accuracy": _mean(deadline_scores),
        "narration_groundedness": _mean(grounded_scores),
    }


def run_smoke(dataset: Path) -> EvalReport:
    cases = _load(dataset)
    smoke_settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(smoke_settings)
    service = TriageService(audit, LocalNoopTracerAdapter(smoke_settings))

    decision_scores: list[float] = []
    for case in cases:
        result = service.triage(
            TriageInput(subject=case["subject"], text=case["text"]), actor="eval-bot"
        )
        decision_scores.append(1.0 if result.severity.value == case["expected_severity"] else 0.0)

    # pii_safety: no raw identifier may survive into any audit record. The pack scan uses the
    # same rows the redactor masks with; the planted-literal check is an independent oracle that
    # fires even if a row is broken (the two-part scorer lesson from the C4 rollout).
    records = audit_texts(audit.log.read_all())
    planted = [case["planted"] for case in cases if case.get("planted")]
    pii_score = pii_safety(records, planted)

    # The contract-extraction vertical: the deterministic engine against a hand-computed oracle,
    # and the register narrator held to the engine's figures. All offline (SDK-free local family).
    contract_cases = _load_scenarios(CONTRACT_DATASET)
    contract = score_contracts(contract_cases)

    results = (
        EvalMetricResult.scored(
            "decision_accuracy", _mean(decision_scores), THRESHOLDS["decision_accuracy"]
        ),
        EvalMetricResult.scored("pii_safety", pii_score, THRESHOLDS["pii_safety"]),
        EvalMetricResult.scored(
            "extraction_accuracy",
            contract["extraction_accuracy"],
            THRESHOLDS["extraction_accuracy"],
        ),
        EvalMetricResult.scored(
            "flag_accuracy", contract["flag_accuracy"], THRESHOLDS["flag_accuracy"]
        ),
        EvalMetricResult.scored(
            "deadline_accuracy", contract["deadline_accuracy"], THRESHOLDS["deadline_accuracy"]
        ),
        EvalMetricResult.scored(
            "narration_groundedness",
            contract["narration_groundedness"],
            THRESHOLDS["narration_groundedness"],
        ),
    )
    return EvalReport(
        dataset=str(dataset), results=results, n_examples=len(cases) + len(contract_cases)
    )


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"CONTRACT_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("CONTRACT_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / model-quality-gate for contract-obligation-extraction.",
        )
    )
