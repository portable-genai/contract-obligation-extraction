"""API request/response schemas (Pydantic) mapped to/from the pure-domain models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..domain.contracts import ContractRegister, register_envelope
from ..domain.models import TriageResult
from ..domain.narration import NarratedNote


class TriageRequest(BaseModel):
    subject: str
    text: str


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class TriageResponse(BaseModel):
    subject: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    #: Where the escalation WENT (rule R8): the Hrz7 review id, or the local queue reference.
    #: Empty only when the result did not escalate. A caller can tell a routed escalation from
    #: a flag that stopped here, which is the whole point of the rule.
    review_ref: str = ""
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, result: TriageResult, *, review_ref: str = "") -> TriageResponse:
        return cls(
            subject=result.subject,
            severity=result.severity.value,
            decision=result.decision.value,
            summary=result.summary,
            requires_human_review=result.requires_human_review,
            review_ref=review_ref,
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class RegisterRequest(BaseModel):
    """Read one contract from the corpus into its obligation register.

    ``contract_id`` names a seed contract (offline, the corpus stands in for uploaded documents).
    ``as_of`` is the reference date the renewal clock evaluates against; omitted, it defaults to
    the corpus reference date so the offline result is deterministic.
    """

    contract_id: str
    as_of: str = ""


class DeadlineModel(BaseModel):
    due_on: str
    kind: str
    status: str
    days_until: int
    notice_days: int
    action_by: str
    in_notice_window: bool
    breached: bool


class ObligationRow(BaseModel):
    obligation_id: str
    text: str
    owner: str
    clause_anchor: str
    clause_number: str
    flags: list[str] = []
    needs_review: bool = False
    deadline: DeadlineModel | None = None
    citation: CitationModel | None = None


class RegisterResponse(BaseModel):
    contract_id: str
    family: str
    counterparty: str
    subject: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    obligations: list[ObligationRow] = []
    #: Candidate texts refused because they cited a clause anchor the contract does not contain.
    dropped: list[str] = []
    flag_counts: dict[str, int] = {}
    as_of: str = ""
    #: The model-narrated (or deterministically fallen-back) register summary. Grounded: every
    #: figure in it comes from the engine, never the model.
    note: str = ""
    note_model_authored: bool = False
    #: Where the escalation WENT (rule R8): the Hrz7 review id or the local queue reference.
    review_ref: str = ""
    citations: list[CitationModel] = []
    #: The versioned wire shape the Rgc8 TPRM system consumes. Carries its own
    #: ``schema_version`` so a downstream consumer pins it; a recorded PROPOSAL until Rgc8 exists.
    feed: dict[str, Any] = {}

    @classmethod
    def from_domain(
        cls,
        register: ContractRegister,
        *,
        note: NarratedNote,
        review_ref: str = "",
    ) -> RegisterResponse:
        return cls(
            contract_id=register.contract_id,
            family=register.family.value,
            counterparty=register.counterparty,
            subject=register.subject,
            severity=register.severity.value,
            decision=register.decision.value,
            summary=register.summary,
            requires_human_review=register.requires_human_review,
            obligations=[_row(row) for row in register.obligations],
            dropped=list(register.dropped),
            flag_counts=dict(register.flag_counts),
            as_of=register.as_of.isoformat(),
            note=note.text,
            note_model_authored=note.model_authored,
            review_ref=review_ref,
            citations=[
                CitationModel(
                    source_id=c.source_id,
                    title=c.title or c.locator or c.source_id,
                    snippet=c.snippet or c.locator,
                )
                for c in register.citations
            ],
            feed=register_envelope(register),
        )


def _row(row: Any) -> ObligationRow:
    deadline = None
    if row.deadline is not None:
        dv = row.deadline
        deadline = DeadlineModel(
            due_on=dv.due_on.isoformat(),
            kind=dv.kind,
            status=dv.status.value,
            days_until=dv.days_until,
            notice_days=dv.notice_days,
            action_by=dv.action_by.isoformat(),
            in_notice_window=dv.in_notice_window,
            breached=dv.breached,
        )
    return ObligationRow(
        obligation_id=row.obligation_id,
        text=row.text,
        owner=row.owner,
        clause_anchor=row.clause_anchor,
        clause_number=row.clause_number,
        flags=list(row.flag_values),
        needs_review=row.needs_review,
        deadline=deadline,
        citation=CitationModel(
            source_id=row.citation.source_id,
            title=row.citation.title or row.citation.locator or row.citation.source_id,
            snippet=row.citation.snippet or row.citation.locator,
        ),
    )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Both are read off the service because the browser cannot know either.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
