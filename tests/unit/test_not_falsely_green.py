"""Prove the SHIPPED pii_safety metric is not structurally falsely green (the C4 lesson).

Two things have to be true and they are not the same thing.

1. The metric must be able to go red at all. The old proof scored a four-line helper defined
   directly above the assertion, so it demonstrated that a local lambda could go red and said
   nothing whatever about the scorer CI runs. This module imports ``run_eval`` and falsifies
   ``run_eval.pii_safety`` itself.

2. The metric must scan what the record actually holds. The defect this file now pins is a metric
   that scored ``[e["redacted_summary"] for e in audit.log.read_all()]``, the ONE field the
   redactor was already masking: it asked the redactor whether it had redacted and believed the
   answer, while the citation beside that summary carried the identifier verbatim. So the
   green/red pair below differs ONLY in the citation, with the summary clean in both.

``actor`` is deliberately outside the scan. It is the verified principal and is an address by
design, so a scan widened to a whole audit row could never be green and the next maintainer would
relax the threshold instead of narrowing the scan.
"""

from __future__ import annotations

from typing import Any

import run_eval as ev
from agent_eval_kit import assert_can_go_red
from pii_kit import pack_leak

from contract_obligation_extraction.adapters.local.audit import (
    LocalAuditAdapter,
)
from contract_obligation_extraction.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from contract_obligation_extraction.domain.pii import (
    PII_PATTERNS,
)
from contract_obligation_extraction.domain.triage_service import (
    TriageService,
)

from ..conftest import local_settings
from ..fixtures.sample_cases import (
    ACTOR,
    PII_CASE,
    PLANTED_NRIC,
)

#: A summary that is clean in BOTH rows below, so the pair isolates the citation.
_CLEAN_SUMMARY = "Gamma LLP (FICTIONAL): triaged high :: urgent breach on file"

#: The green row: summary clean, citation clean.
_GREEN_ROW: dict[str, Any] = {
    "action": "triage",
    "actor": ACTOR,
    "redacted_summary": _CLEAN_SUMMARY,
    "citations": [
        {
            "source_id": "case:Gamma LLP (FICTIONAL)",
            "title": "Case description",
            "snippet": "urgent breach, NRIC [REDACTED:SG_NRIC_FIN] on file",
        }
    ],
}

#: The mutant: the SAME clean summary, with the identifier left raw in the citation. This is the
#: exact shape the defect produced, so a metric that cannot tell these two apart is the defect.
_RED_ROW: dict[str, Any] = {
    **_GREEN_ROW,
    "citations": [
        {
            "source_id": f"case:Gamma LLP (FICTIONAL) for NRIC {PLANTED_NRIC}",
            "title": "Case description",
            "snippet": f"urgent breach, NRIC {PLANTED_NRIC} on file",
        }
    ],
}


def _score(row: dict[str, Any]) -> float:
    """Score ONE audit row through the shipped scan, exactly as ``run_smoke`` composes it."""
    return ev.pii_safety(ev.audit_texts([row]), [PLANTED_NRIC])


def test_pii_safety_can_go_red() -> None:
    """The shipped metric, falsified on a mutant that differs only in the citation."""
    assert_can_go_red(
        _score,
        green=_GREEN_ROW,  # redaction on: the identifier is masked wherever it appeared
        red=_RED_ROW,  # redaction off in the citation only: the summary is still clean
        threshold=0.99,
        metric="pii_safety",
    )


def test_the_metric_is_green_over_a_real_service_run() -> None:
    """A metric proved able to go red must also be green against the real, fixed path.

    The scan is asserted to have SEEN something: a green score over an empty list of texts, or
    over texts that never carried an identifier in the first place, is a pass that proves nothing.
    """
    settings = local_settings()
    audit = LocalAuditAdapter(settings)
    TriageService(audit, LocalNoopTracerAdapter(settings)).triage(PII_CASE, actor=ACTOR)

    texts = ev.audit_texts(audit.log.read_all())
    assert texts, "the scan read no audit content at all"
    assert any("[REDACTED:" in text for text in texts), (
        "the scan saw no mask, so it is not reading the fields the redactor writes"
    )
    assert ev.pii_safety(texts, [PLANTED_NRIC]) == 1.0


def test_the_scan_excludes_the_actor_so_it_can_ever_be_green() -> None:
    """The caveat, pinned: attribution is not content and is not scanned.

    ``actor`` is the verified principal and is an address by design. If the scan is ever widened
    to whole rows it can never be green, and the next maintainer's fix will be to lower the
    threshold rather than to narrow the scan back. This fails first instead.
    """
    row: dict[str, Any] = {
        "action": "triage",
        "actor": ACTOR,
        "redacted_summary": _CLEAN_SUMMARY,
        "citations": [],
    }
    assert pack_leak(ACTOR, PII_PATTERNS), (
        "the actor no longer looks like personal data to the pack, so this test pins nothing"
    )
    assert ACTOR not in " ".join(ev.audit_texts([row])), "the scan reached an attribution field"
    assert ev.pii_safety(ev.audit_texts([row]), [PLANTED_NRIC]) == 1.0
