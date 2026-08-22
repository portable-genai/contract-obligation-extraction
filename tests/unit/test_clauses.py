"""Clause segmentation: stable anchors, preamble handling and the unstructured fallback.

The whole linkage guarantee rests on anchors being a pure function of the clause NUMBER, not of
parse position, so these lock that down: inserting a recital does not renumber clause 1, a body
with no numbered heading still yields one anchorable unit, and re-segmentation is byte-identical.
"""

from __future__ import annotations

from contract_obligation_extraction.domain.clauses import (
    anchor_for,
    clause_by_anchor,
    segment_clauses,
)

_BODY = """Preamble text that anchors to nothing.

1. Term
The agreement runs for a year.

2.1 Fees
Fees are due in thirty days.

10.3.2 Deep Clause
A deeply numbered clause.
"""


def test_segments_at_numbered_headings_and_preamble_is_dropped() -> None:
    clauses = segment_clauses("c-1", _BODY)
    numbers = [c.number for c in clauses]
    assert numbers == ["1", "2.1", "10.3.2"], "preamble is not a numbered clause and must not admit"


def test_anchor_is_derived_from_the_clause_number_not_the_ordinal() -> None:
    clauses = segment_clauses("c-1", _BODY)
    assert clauses[1].anchor == anchor_for("c-1", "2.1") == "c-1#cl-2.1"
    # Prepending a recital changes ordinals but must not change the anchor of clause 2.1.
    shifted = segment_clauses("c-1", "0. Recital\nnew recital\n\n" + _BODY)
    by_anchor = clause_by_anchor(shifted)
    assert "c-1#cl-2.1" in by_anchor


def test_a_body_with_no_numbered_heading_yields_one_fallback_clause() -> None:
    clauses = segment_clauses("letter", "This letter agreement has no numbered clauses at all.")
    assert len(clauses) == 1
    assert clauses[0].number == "0"


def test_segmentation_is_byte_identical_across_runs() -> None:
    first = segment_clauses("c-1", _BODY)
    second = segment_clauses("c-1", _BODY)
    assert first == second


def test_empty_body_yields_no_clauses() -> None:
    assert segment_clauses("c-1", "   \n  \n") == ()
