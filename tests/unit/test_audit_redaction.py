"""Nothing a contract carried survives into a sink, and the sinks are counted.

A contract is client document text end to end: the counterparty names a person, a notices clause
carries an address, and the extractor lifts both verbatim. The register path has FOUR sinks and
they are not one sink:

* the bound narration model, which is handed the register's subject;
* the WORM audit record, which is immutable and long-retained by design;
* the outbound human-review-console review payload, which crosses to a SHARED console;
* the response the API returns to the caller.

The audit write and the review payload each had their own redaction and each covered only itself,
so a test that read only the audit row would have called the model boundary clean. These
assertions therefore read every sink from ONE real run, through ``flow.run_contract_register``
rather than through a re-implementation of it, and scan with two independent oracles: the shared
pack (the same rows the redactor masks with) and the planted literals (which fire even if a
pattern row is broken).

``actor`` is deliberately exempt. It is the verified principal and is an address by design, so a
blanket scan over a whole audit row can never be green; the scan reads the CONTENT fields and
``test_the_actor_is_kept_verbatim`` pins that so nobody widens it and relaxes the assertion
instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from hex_service_kit import to_jsonable
from pii_kit import pack_leak
from review_kit import Review

from contract_obligation_extraction.adapters._review_payload import (
    result_to_review,
)
from contract_obligation_extraction.adapters.local.audit import (
    LocalAuditAdapter,
)
from contract_obligation_extraction.adapters.local.generation import (
    LocalGenerationAdapter,
)
from contract_obligation_extraction.adapters.local.review_router import (
    LocalReviewRouter,
)
from contract_obligation_extraction.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from contract_obligation_extraction.api.schemas import (
    RegisterResponse,
)
from contract_obligation_extraction.config import (
    Container,
    Settings,
)
from contract_obligation_extraction.domain.pii import (
    PII_PATTERNS,
)
from contract_obligation_extraction.domain.triage_service import (
    TriageService,
)
from contract_obligation_extraction.flow import (
    RegisterOutcome,
    run_contract_register,
)
from contract_obligation_extraction.ports.extraction import (
    ExtractionRequest,
    ExtractionResult,
    ProposedObligation,
)
from contract_obligation_extraction.ports.generation import (
    GenerationRequest,
    GenerationResponse,
)

from ..conftest import local_settings
from ..fixtures.sample_cases import (
    ACTOR,
    PII_CONTRACT,
    PII_SUBJECT_CASE,
    PLANTED_EMAIL,
    PLANTED_NRIC,
    TENANT,
)

#: Both planted literals, as the independent oracle. A pattern pack that agrees with itself is
#: not evidence; a literal that was in the input and is not in the output is.
PLANTED: tuple[str, ...] = (PLANTED_NRIC, PLANTED_EMAIL)


#: The outbound review's ATTRIBUTION field, excluded from the payload scan for the same reason
#: ``actor`` is excluded from the audit scan: the maker is the verified principal and is an
#: address by design, so a genuinely blanket scan could never go green. ``tenant`` is a partition
#: label the server derives, not client text. See :func:`assert_payload_clean`.
ATTRIBUTION_FIELDS = frozenset({"maker", "tenant"})


def assert_clean(label: str, *texts: str) -> None:
    """Fail with the offending text when either oracle sees a raw identifier in ``texts``."""
    for text in texts:
        found = pack_leak(text, PII_PATTERNS)
        assert not found, f"{label}: the shared pack found {found} in {text!r}"
        for token in PLANTED:
            assert token not in text, f"{label}: the planted {token} survived into {text!r}"


def assert_payload_clean(label: str, review: Review) -> None:
    """Scan the WHOLE serialised review, minus the named attribution fields.

    Serialised off the dataclass rather than from a hand-listed set of names, so a field added to
    ``Review`` later is scanned by DEFAULT instead of by somebody remembering to extend this.
    That is the entire lesson of ``case_ref`` and ``source_key``: listing subject, summary and
    the citation fields is exactly the set a reader thinks of as content, and the two fields
    named like keys carry the raw subject straight past it.
    """
    body = {
        name: value for name, value in to_jsonable(review).items() if name not in ATTRIBUTION_FIELDS
    }
    assert_clean(label, json.dumps(body, sort_keys=True, default=str))


class _TapExtraction:
    """A document extractor: it lifts candidate text verbatim from the clause it read.

    Stands in for Document AI plus the long-context read, which is what the managed binding is.
    The point of the tap is the lifting: the local corpus adapter replays hand-written proposals
    that happen to carry no personal data, so it could never show what a real extractor returns
    for a real contract.
    """

    def __init__(self, settings: Settings) -> None:
        self.seen: list[ExtractionRequest] = []

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        self.seen.append(request)
        clause = {c.number: c for c in request.clauses}
        return ExtractionResult(
            candidates=(
                ProposedObligation(
                    # Clause 2 first, deliberately: the outbound payload de-duplicates citations
                    # by locator and every clause of one contract shares it, so a leak sitting
                    # behind a clean first citation would never reach the assertion.
                    text=clause["2"].text.replace("\n", " "),
                    clause_anchor=clause["2"].anchor,
                    owner=f"Kai Tan <{PLANTED_EMAIL}>",
                    proposed_flags=("audit_step_in",),
                ),
                ProposedObligation(
                    text="Bank gives at least 60 days notice before the 15 May 2026 renewal.",
                    clause_anchor=clause["1"].anchor,
                    owner="cro-office",
                    due_on="2026-05-15",
                    due_kind="renewal_notice",
                    notice_days=60,
                    proposed_flags=("termination_renewal",),
                ),
            ),
            model="tap-extractor",
        )


class _TapGeneration:
    """The bound narration model, recording every request the service hands it."""

    def __init__(self, settings: Settings) -> None:
        self.seen: list[GenerationRequest] = []
        self._real = LocalGenerationAdapter(settings)

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.seen.append(request)
        return self._real.generate(request)


@dataclass(slots=True)
class _Run:
    """One real register run plus the taps on the two ports that leave the process."""

    outcome: RegisterOutcome
    extraction: _TapExtraction
    generation: _TapGeneration
    audit: LocalAuditAdapter
    router: LocalReviewRouter
    settings: Settings = field(default_factory=local_settings)

    @property
    def audit_rows(self) -> list[dict[str, object]]:
        return list(self.audit.log.read_all())

    @property
    def audit_content(self) -> list[str]:
        """The audit CONTENT fields: the summary and every citation field. Never the actor."""
        texts: list[str] = []
        for row in self.audit_rows:
            texts.append(str(row.get("redacted_summary", "")))
            texts.append(json.dumps(row.get("citations", []), sort_keys=True))
        return texts


def _run_register() -> _Run:
    """Drive the REAL flow over the planted contract, with the two model ports tapped."""
    settings = local_settings()
    container = Container(settings)
    extraction = _TapExtraction(settings)
    generation = _TapGeneration(settings)
    audit = LocalAuditAdapter(settings)
    router = LocalReviewRouter(settings)
    # cached_property reads the instance dict first, so this binds the taps without a subclass
    # that could diverge from the container the surfaces actually build.
    container.__dict__.update(
        extraction=extraction,
        generation=generation,
        audit=audit,
        review_router=router,
        tracer=LocalNoopTracerAdapter(settings),
    )
    outcome = run_contract_register(
        container, PII_CONTRACT, as_of=date(2026, 6, 1), actor=ACTOR, tenant=TENANT
    )
    return _Run(
        outcome=outcome,
        extraction=extraction,
        generation=generation,
        audit=audit,
        router=router,
        settings=settings,
    )


def test_the_audit_record_keeps_nothing_the_redaction_removed() -> None:
    """The summary and the citations are ONE record: masking one and not the other stores both."""
    run = _run_register()
    assert run.audit_rows, "a register run that wrote no audit row proves nothing"
    assert_clean("audit", *run.audit_content)
    assert any("[REDACTED:" in text for text in run.audit_content), (
        "the scan saw no mask at all, so it may simply be reading the wrong fields"
    )


def test_the_narration_model_is_never_handed_the_raw_contract() -> None:
    """The model boundary is a SEPARATE sink: the audit fix does not reach it."""
    run = _run_register()
    assert run.generation.seen, "the narration port was never called; the tap proves nothing"
    for request in run.generation.seen:
        assert_clean("narration prompt", request.prompt, request.system)
        assert_clean("narration facts", *(value for _key, value in request.facts))


def test_the_whole_outbound_review_payload_is_clean() -> None:
    """human-review-console is a SHARED console, and every field of the payload lands on it.

    A locator or a title is as readable there as a snippet, and so are ``case_ref`` and
    ``source_key``, which are built from the subject and whose structural names are the only
    reason anyone read them as something other than content.
    """
    run = _run_register()
    pending = run.router.outbox.pending()
    assert pending, "the register escalated but nothing was routed; there is nothing to scan"
    review = pending[0].review
    assert review.citations, "a review with no citation cannot show a leak or a provenance"
    assert_payload_clean("review", review)


def test_the_returned_register_carries_no_raw_identifier() -> None:
    """The API response is the fourth sink, and it is the one a browser caches."""
    run = _run_register()
    body = RegisterResponse.from_domain(
        run.outcome.register, note=run.outcome.note, review_ref=run.outcome.review_ref
    ).model_dump()
    assert body["obligations"], "an empty register would pass every scan below vacuously"
    assert_clean("api response", json.dumps(body, sort_keys=True, default=str))


def test_the_locator_path_is_masked_when_the_subject_carries_the_identifier() -> None:
    """A citation locator is built from client text (``case:<subject>``), so it is content."""
    settings = local_settings()
    audit = LocalAuditAdapter(settings)
    service = TriageService(audit, LocalNoopTracerAdapter(settings))
    result = service.triage(PII_SUBJECT_CASE, actor=ACTOR)

    rows = list(audit.log.read_all())
    assert rows, "the triage wrote no audit row"
    for row in rows:
        assert_clean(
            "audit (subject case)",
            str(row.get("redacted_summary", "")),
            json.dumps(row.get("citations", []), sort_keys=True),
        )

    router = LocalReviewRouter(settings)
    router.route(result, maker=ACTOR, tenant=TENANT)
    assert_payload_clean("review (subject case)", router.outbox.pending()[0].review)


def test_the_review_source_key_is_stable_so_a_retry_stays_idempotent() -> None:
    """The named cost of reusing the masked subject: the key must still survive a retry.

    ``pii_kit.redact`` substitutes a fixed literal token per pattern, with no hash and no salt,
    so the same subject always yields the same key. Pinned rather than assumed, because a masking
    style that ever became random would silently turn every retried delivery into a second review
    on the console, and the collapse trade-off is only defensible while the key is stable.
    """
    settings = local_settings()
    service = TriageService(LocalAuditAdapter(settings), LocalNoopTracerAdapter(settings))
    result = service.triage(PII_SUBJECT_CASE, actor=ACTOR)

    keys = {result_to_review(result, maker=ACTOR, tenant=TENANT).source_key for _ in range(200)}
    assert len(keys) == 1, f"the idempotency key is not stable under redaction: {keys}"
    assert PLANTED_NRIC not in keys.pop()


def test_the_actor_is_kept_verbatim() -> None:
    """The caveat, pinned: attribution is not content, and masking it erases who acted.

    ``ACTOR`` is an address, so a blanket pack scan over a whole audit row can never be green.
    That is a reason to scan the content fields, never a reason to relax the threshold, and this
    test exists so the next maintainer meets the rule before they widen the scan.
    """
    run = _run_register()
    actors = [str(row.get("actor", "")) for row in run.audit_rows]
    assert actors == [ACTOR], f"the audit lost the verified principal: {actors}"
    assert pack_leak(ACTOR, PII_PATTERNS), (
        "the actor is expected to look like personal data to the pack; if it no longer does, "
        "this test has stopped pinning anything"
    )
