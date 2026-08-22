"""Deterministic clause segmentation with stable anchor ids (pure stdlib).

The consequential guarantee of this vertical is that every extracted obligation, date and risk
flag links back to the exact clause it came from. That link is only trustworthy if the clause
boundaries and their anchor ids are a PURE, replayable function of the contract text, computed by
code and never by the model: the model may quote a clause number, but whether that number names a
real clause is decided here.

A contract body is split at numbered-heading boundaries (``1.``, ``2.1``, ``10.3.2`` ...). Each
segment becomes a :class:`Clause` whose ``anchor`` is derived from the clause NUMBER in the
document, not from its position in the parse, so inserting a recital above clause 1 does not
renumber every anchor below it. A body with no numbered headings falls back to a single ordinal
anchor, so an unstructured letter agreement is still first class.

Nothing here reads a model, a clock or a network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "Clause",
    "anchor_for",
    "clause_by_anchor",
    "segment_clauses",
]

#: A numbered clause heading at the start of a line: ``1.``, ``2.1``, ``10.3.2 Heading text``.
#: The number (with its dotted sub-parts) is captured; the trailing heading text is optional.
_HEADING = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\.?\s+(?P<heading>\S.*)$")


@dataclass(frozen=True, slots=True)
class Clause:
    """One segmented clause of a contract, with a stable anchor into its source document.

    ``anchor`` is the load-bearing id: an extracted item cites it, and admission refuses any item
    whose cited anchor is not one this segmentation produced. ``number`` is the clause number as
    written in the document (``"2.1"``); ``ordinal`` is its 1-based position in the parse, used
    only for the fallback anchor when a document carries no numbered headings.
    """

    contract_id: str
    number: str
    heading: str
    text: str
    ordinal: int

    @property
    def anchor(self) -> str:
        """This clause's stable anchor id (``<contract_id>#cl-<number>``)."""
        return anchor_for(self.contract_id, self.number)

    @property
    def body(self) -> str:
        """The heading and clause text as one block, for a citation snippet or a display."""
        return f"{self.number}. {self.heading}\n{self.text}".strip()


def anchor_for(contract_id: str, number: str) -> str:
    """Build the stable anchor id for a clause number within a contract.

    A pure function of the two identifiers, exposed so a caller (an extractor, a test oracle)
    constructs the SAME anchor the segmentation does rather than guessing its format.
    """
    return f"{contract_id}#cl-{number}"


def segment_clauses(contract_id: str, body: str) -> tuple[Clause, ...]:
    """Split a contract body into clauses at numbered-heading boundaries (pure, replayable).

    Text before the first numbered heading (a preamble or recitals block) is not a numbered
    clause and is dropped from the clause set, because nothing anchors to it. A body with no
    numbered heading at all yields a single ``cl-0`` clause carrying the whole text, so an
    unstructured agreement still segments to exactly one anchorable unit.
    """
    lines = body.splitlines()
    heads: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = _HEADING.match(line.strip())
        if match:
            heads.append((index, match.group("number"), match.group("heading").strip()))

    if not heads:
        stripped = body.strip()
        if not stripped:
            return ()
        return (Clause(contract_id, "0", "", stripped, 1),)

    clauses: list[Clause] = []
    for position, (start, number, heading) in enumerate(heads):
        end = heads[position + 1][0] if position + 1 < len(heads) else len(lines)
        text = "\n".join(lines[start + 1 : end]).strip()
        clauses.append(
            Clause(
                contract_id=contract_id,
                number=number,
                heading=heading,
                text=text,
                ordinal=position + 1,
            )
        )
    return tuple(clauses)


def clause_by_anchor(clauses: tuple[Clause, ...]) -> dict[str, Clause]:
    """Index clauses by their anchor id for O(1) linkage validation during admission."""
    return {clause.anchor: clause for clause in clauses}
