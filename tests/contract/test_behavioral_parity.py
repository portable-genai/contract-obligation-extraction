"""Behavioural parity: the SAME canonical request through every implementation of every port.

``test_port_parity`` proves each adapter *satisfies* its Protocol. Structural conformance is
cheap to fake: a family of methods that all return ``None`` passes it. This suite proves the
stronger claim the no-lock-in promise (P-02) actually rests on, for one canonical request per
port:

* ``local``  : the offline family ANSWERS. It records what it was given, resolves a real
  principal, produces a routing reference. A silently empty offline stack is the failure mode
  that lets a repo ship a green gate and no working profile.
* ``onprem`` : the migration placeholder RAISES ``NotImplementedError``. A placeholder that
  returned successfully would be a false portability claim, and for the review router it would
  convert every consequential result into an unreviewed one.
* ``gcp``    : the managed family, with nothing reachable, refuses in its documented way. Never
  a silent success.

Plus the boundary-payload proof: what the offline family puts on the wire when it flushes is
exactly what the managed family submits, because both build it from the same shared converter.
That is what makes "the offline profile exercises the R8 path" a real statement rather than a
different code path that happens to be green.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from review_kit import ReviewClient

from contract_obligation_extraction.adapters._review_payload import (
    result_to_review,
)
from contract_obligation_extraction.config import (
    build_container,
)
from contract_obligation_extraction.domain.triage_service import (
    TriageService,
)

from .canonical import CANONICAL_CALLS, CANONICAL_RESULT
from tests.conftest import local_settings
from tests.fixtures import sample_cases

#: A loopback console, so the kit's own https-off-loopback rule does not demand a bearer here.
_FAKE_CONSOLE = "http://127.0.0.1:8086"


def _adapter(port: str, profile: str, **overrides: Any) -> Any:
    return getattr(build_container(local_settings(profile=profile, **overrides)), port)


@pytest.mark.parametrize("port", sorted(CANONICAL_CALLS))
def test_the_offline_family_actually_answers(port: str) -> None:
    case = CANONICAL_CALLS[port]
    adapter = _adapter(port, "local")
    result = case.invoke(adapter)
    assert case.answered(adapter, result), (
        f"the local {port} adapter did not {case.detail}; an offline family that merely fails "
        "to raise is not a working profile"
    )


@pytest.mark.parametrize("port", sorted(CANONICAL_CALLS))
def test_the_onprem_family_raises_rather_than_pretending(port: str) -> None:
    case = CANONICAL_CALLS[port]
    if not case.managed_refusal:
        # A port documented not to refuse when managed does not refuse on-prem either:
        # see the tracer's PortCase. Exercised rather than skipped, so a tracer that
        # starts raising fails here.
        case.invoke(_adapter(port, "onprem"))
        return
    with pytest.raises(NotImplementedError):
        case.invoke(_adapter(port, "onprem"))


@pytest.mark.parametrize("port", sorted(CANONICAL_CALLS))
def test_the_managed_family_refuses_rather_than_succeeding_offline(
    port: str, no_cloud_sdk: None
) -> None:
    """With no SDK and no console, every managed adapter must fail in its documented way."""
    case = CANONICAL_CALLS[port]
    if not case.managed_refusal:
        # An EMPTY managed_refusal is the strongest claim here: that adapter must COMPLETE
        # offline rather than raise, because an exporter fault must never become a
        # request fault.
        case.invoke(_adapter(port, "gcp", review_url=""))
        return
    with pytest.raises(case.managed_refusal):
        case.invoke(_adapter(port, "gcp", review_url=""))


# --------------------------------------------------------------------------- #
# The boundary payload: offline and managed put the SAME bytes on the wire
# --------------------------------------------------------------------------- #
def test_the_offline_outbox_flushes_the_payload_the_managed_router_would_submit() -> None:
    router = _adapter("review_router", "local")
    router.route(CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)

    posted: list[dict[str, Any]] = []

    def _recording_transport(url: str, body: bytes, headers: Any, timeout: float) -> dict[str, Any]:
        posted.append({"url": url, "payload": json.loads(body.decode("utf-8"))})
        return {"review_id": "rev-1", "tenant": sample_cases.TENANT, "state": "pending"}

    submitted = router.outbox.flush(ReviewClient(_FAKE_CONSOLE, transport=_recording_transport))

    assert [s.review_id for s in submitted] == ["rev-1"]
    assert router.outbox.pending() == (), "a flushed entry must not stay queued"
    expected = result_to_review(
        CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT
    ).to_payload()
    assert posted[0]["payload"] == expected, (
        "the offline family enqueued a payload different from the one the managed family "
        "submits, so the offline R8 path proves nothing about the managed one"
    )


def test_the_payload_that_reaches_the_wire_is_redacted_whichever_family_built_it() -> None:
    """Hrz7 is a shared sink, so this holds for every family, not only the one under demo."""
    wire_container = build_container(local_settings())
    service = TriageService(wire_container.audit, wire_container.tracer)
    result = service.triage(sample_cases.PII_CASE, actor=sample_cases.ACTOR)
    payload = repr(
        result_to_review(result, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT).to_payload()
    )
    assert sample_cases.PLANTED_NRIC not in payload
    assert "REDACTED" in payload


# --------------------------------------------------------------------------- #
# End to end: one profile line swaps the whole stack, the domain untouched
# --------------------------------------------------------------------------- #
def test_the_whole_pipeline_answers_on_local_and_fails_fast_on_onprem() -> None:
    local = build_container(local_settings())
    result = TriageService(local.audit, local.tracer).triage(
        sample_cases.ESCALATING_CASE, actor=sample_cases.ACTOR
    )
    assert result.requires_human_review is True
    assert result.citations, "an offline answer must still be cited"
    assert local.review_router.route(result, maker=sample_cases.ACTOR)

    onprem = build_container(local_settings(profile="onprem"))
    with pytest.raises(NotImplementedError):
        TriageService(onprem.audit, onprem.tracer).triage(
            sample_cases.ESCALATING_CASE, actor=sample_cases.ACTOR
        )
