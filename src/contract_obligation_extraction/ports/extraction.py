"""ExtractionPort: the Document AI + long-context model boundary for contract reading.

This is where the model lives on the extraction path, and its contract is deliberately narrow:
it turns a segmented contract (clauses with stable anchors) into CANDIDATE obligations, dates and
proposed flags, and nothing more. It decides nothing consequential. The engine
(:mod:`..domain.contracts`) owns admission: it refuses a candidate whose cited clause anchor is
not real, dedups on the shared kernel key, validates every proposed flag against the frozen
taxonomy, and routes an ambiguous proposal to a human. So a model that invents a clause anchor or
a flag changes nothing a caller relies on.

The domain stays pure: this is a Protocol. The adapters (not this module) reach Document AI and a
managed model under the ``gcp`` profile with lazy imports, answer deterministically from a fixture
offline, and fail fast on-premises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

__all__ = [
    "ClauseInput",
    "ExtractionPort",
    "ExtractionRequest",
    "ExtractionResult",
    "ProposedObligation",
]


@dataclass(frozen=True, slots=True)
class ClauseInput:
    """One segmented clause handed to the extractor: its anchor and its text.

    The anchor is supplied by the engine's segmentation, never invented by the model: the model
    reads clause text and quotes back the anchor it believes an obligation sits in, and admission
    checks that quote against this set.
    """

    anchor: str
    number: str
    heading: str
    text: str


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """One contract to read: its identity, its family and its segmented clauses."""

    contract_id: str
    family: str
    counterparty: str
    clauses: tuple[ClauseInput, ...]
    max_output_tokens: int = 4096


@dataclass(frozen=True, slots=True)
class ProposedObligation:
    """One candidate obligation the model proposes, with the clause anchor it claims as its source.

    Every field is a PROPOSAL. ``clause_anchor`` is validated against the real segmentation;
    ``proposed_flags`` are validated against the taxonomy; ``ambiguous`` is the model's own
    signal that it is unsure, which the engine turns into a needs-review state rather than a
    default. ``due_on`` is an ISO date string or empty; ``notice_days`` is a renewal/termination
    notice period in days, ``0`` when none was found.
    """

    text: str
    clause_anchor: str
    owner: str = ""
    due_on: str = ""
    due_kind: str = ""
    notice_days: int = 0
    proposed_flags: tuple[str, ...] = ()
    ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """The model's raw proposals for a contract. Consequential admission happens in the engine."""

    candidates: tuple[ProposedObligation, ...] = field(default_factory=tuple)
    model: str = ""


@runtime_checkable
class ExtractionPort(Protocol):
    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Return the model's candidate obligations for ``request`` (proposals, never decisions).

        Implementations never admit anything: they read and propose. A failure to reach the model
        or the parser is a raised error (the managed family) or a raised ``NotImplementedError``
        (the on-premises placeholder), never a silently empty result a caller could mistake for a
        contract that genuinely carries no obligations.
        """
        ...
