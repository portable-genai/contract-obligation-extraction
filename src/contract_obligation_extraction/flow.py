"""The contract-register flow: one orchestration the API, CLI and agent all call.

Reading a contract into its register is the same six steps whoever asks: build the extraction
request from the contract's segmented clauses, ask the bound extraction adapter to PROPOSE, admit
the proposals through the deterministic engine, narrate the result with the bound model, and route
the consequential result to human-review-console (rule R8). Putting those steps in one place is what
keeps the three surfaces from drifting into three subtly different pipelines, and it keeps the R8
routing on every path rather than on whichever surface someone remembered.

This module lives above the pure domain because it wires the container's adapters; it imports no
web framework and no cloud SDK, so it stays testable offline.

It is also where the redaction boundary sits for this path, because this is where the edge ends. A
contract is client document text end to end: the counterparty names a party, a notices clause names
a person, and the extractor lifts both verbatim. Downstream of here that text reaches four sinks
(the narration model, the WORM audit record, the outbound human-review-console payload and the API
response), so it is masked ONCE, here, rather than four times at four sinks that each have to
remember. See :func:`_redacted_document` and :func:`_redacted_proposals`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from pii_kit import redact

from .config import Container
from .domain.contracts import Contract, ContractRegister, RegisterService
from .domain.kernel import Citation as AuditCitation
from .domain.models import TriageResult
from .domain.narration import NarratedNote, NarrationService
from .domain.pii import PII_PATTERNS
from .ports.extraction import ClauseInput, ExtractionRequest, ExtractionResult

__all__ = ["RegisterOutcome", "extraction_request_for", "run_contract_register"]

#: One span per contract read. Structural attributes only: see :func:`run_contract_register`.
_REGISTER_SPAN = "obligations.register"


@dataclass(frozen=True, slots=True)
class RegisterOutcome:
    """One contract read: the consequential register, its narrated summary and the R8 routing."""

    register: ContractRegister
    note: NarratedNote
    review_ref: str


def extraction_request_for(contract: Contract) -> ExtractionRequest:
    """Build the extraction request the adapter reads, from the contract's real segmentation."""
    return ExtractionRequest(
        contract_id=contract.contract_id,
        family=contract.family.value,
        counterparty=contract.counterparty,
        clauses=tuple(
            ClauseInput(
                anchor=clause.anchor,
                number=clause.number,
                heading=clause.heading,
                text=clause.text,
            )
            for clause in contract.clauses()
        ),
    )


def _redacted_document(contract: Contract) -> Contract:
    """The contract as everything downstream of the edge may keep it: its text masked.

    The extractor READS the raw document, which is the one thing at the edge that has to: it is a
    layout parse plus a long-context read, and a masked contract is not the contract. Everything
    the register is then built FROM is this masked view, because the register's own fields are
    where the document leaves: ``counterparty`` becomes the subject the narration model is
    prompted with, ``title`` and each clause's text become citation titles and snippets, and all
    of it lands in the audit record, the human-review-console payload and the response.

    ``body`` is masked rather than each segmented clause, so segmentation runs over the masked
    text and no unmasked slice can survive in a snippet. Anchors are derived from clause NUMBERS,
    which redaction does not touch, so the extractor's cited anchors still validate against this
    segmentation exactly as they did against the raw one.
    """
    return replace(
        contract,
        counterparty=redact(contract.counterparty, PII_PATTERNS),
        title=redact(contract.title, PII_PATTERNS),
        body=redact(contract.body, PII_PATTERNS),
    )


def _redacted_proposals(result: ExtractionResult) -> ExtractionResult:
    """Mask the extractor's output where it crosses OUT of the edge, before anything reads it.

    ``text`` is a candidate obligation the extractor lifted from a clause and ``owner`` is a party
    it named, so both are raw document text however structural they look. They become register
    rows, dropped-candidate texts and the figures behind every downstream sink. The engine's
    consequential work is untouched by masking: admission keys off the cited clause anchor, the
    taxonomy validates flag strings and the clock reads ISO dates, none of which redaction can
    alter.
    """
    return ExtractionResult(
        candidates=tuple(
            replace(
                candidate,
                text=redact(candidate.text, PII_PATTERNS),
                owner=redact(candidate.owner, PII_PATTERNS),
            )
            for candidate in result.candidates
        ),
        model=result.model,
    )


def _register_to_review(register: ContractRegister) -> TriageResult:
    """Project a consequential register onto the shared R8 review envelope, at the surface.

    The review path is shared across the fleet and speaks the kernel result shape, so the register
    is projected onto it here rather than the pure domain importing a surface type. Kit citations
    become audit-envelope citations; the fields carry across unchanged.
    """
    return TriageResult(
        subject=register.subject,
        severity=register.severity,
        decision=register.decision,
        summary=register.summary,
        requires_human_review=register.requires_human_review,
        citations=tuple(
            AuditCitation(
                source_id=c.source_id,
                title=c.title or c.locator or c.source_id,
                snippet=c.snippet or c.locator,
            )
            for c in register.citations[:8]
        ),
    )


def run_contract_register(
    container: Container,
    contract: Contract,
    *,
    as_of: date,
    actor: str,
    tenant: str = "",
) -> RegisterOutcome:
    """Read one contract into its register, narrate it, and route it to human-review-console when
    consequential.

    The numbers are the deterministic engine's; the bound model only PROPOSES the candidates and
    NARRATES the result, and the narration is discarded unless it validates and every figure in it
    is one the engine produced. Rule R8: a register carrying any material finding escalates and is
    routed here, in the same call, with ``actor`` (the verified principal) as the maker.

    The whole path runs inside one span. Its attributes are STRUCTURAL only, never the
    counterparty, a clause's text, a register row or any narration: a trace backend is not the
    WORM audit trail. It has no redaction stage, a wider read audience and no retention rule
    written against a regulator's requirement, so anything content-shaped that reaches a span
    has left the boundary the register's redaction exists to hold, and left it silently.

    The bound extractor is handed the RAW contract, because reading the document is what it is
    for. Everything it hands back, and the document text the register itself is built from, is
    masked as it crosses out of the edge (:func:`_redacted_proposals`,
    :func:`_redacted_document`), so the narration model, the audit record, the human-review-console
    payload and
    the response are all covered by one redaction rather than by four that must agree.
    """
    with container.tracer.span(
        _REGISTER_SPAN,
        action="register",
        actor=actor,
        tenant=tenant or contract.tenant,
        family=contract.family.value,
    ):
        proposals = container.extraction.extract(extraction_request_for(contract))
        register = RegisterService(container.audit).build(
            _redacted_document(contract),
            _redacted_proposals(proposals),
            as_of=as_of,
            actor=actor,
        )
        note = NarrationService(container.generation).narrate(register)
        review_ref = ""
        if register.requires_human_review:
            review_ref = container.review_router.route(
                _register_to_review(register), maker=actor, tenant=tenant or contract.tenant
            )
        return RegisterOutcome(register=register, note=note, review_ref=review_ref)
