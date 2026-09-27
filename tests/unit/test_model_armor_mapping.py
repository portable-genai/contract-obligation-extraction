"""The Model Armor adapter against the REAL ``modelarmor_v1`` types, offline, no credential.

The mapping from a sanitize response to a verdict is the one line of the managed guardrail that
decides whether anything is ever blocked, and it used to be proved by nothing: the adapter read
``str(filter_match_state)`` and looked for ``MATCH_FOUND`` in it. ``filter_match_state`` is a
proto-plus ``IntEnum``, and from Python 3.11 ``str()`` of an ``IntEnum`` member is its NUMBER,
so the string was ``"2"``, the test never matched, and every prompt was allowed. A test built
on a plain-string stand-in for the enum would have passed over exactly that defect, which is
why every response here is built from the SDK's own message and enum types. The SDK-free half,
``test_model_armor_verdict_mirror.py``, uses ``IntEnum`` mirrors whose ``str()`` behaves the same
way, and this module pins those mirrors to the real enums.

Only the transport is replaced: a recording client that returns a real response message, or
raises a real ``google.api_core`` error, in place of the network call.

WHY THIS MODULE MAY NOT SILENTLY SKIP. ``google-cloud-modelarmor`` is in
``requirements-gcp.lock`` and not in ``requirements-dev.lock``, so the SDK-free ``make gate``
cannot import it, and there this module skips. Where the SDK IS installed, set
``CONTRACT_REQUIRE_MODEL_ARMOR_SDK=1`` and a missing SDK becomes a hard
ERROR instead. Run it that way against the runtime lock after any change to the adapter or to
the SDK pin (docs/runbook.md, "Guardrail (rule R1)").
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from contract_obligation_extraction.adapters.gcp.guardrail import (
    ModelArmorGuardrailAdapter,
)
from contract_obligation_extraction.domain.errors import GuardrailBlockedError
from contract_obligation_extraction.domain.kernel import Decision, Direction
from contract_obligation_extraction.domain.models import TriageInput
from contract_obligation_extraction.domain.triage_service import TriageService

from tests.conftest import local_settings
from tests.fixtures import model_armor_enums

#: Set to "1" wherever the runtime lockfile IS installed, so absence is an error, not a skip.
#: An exact-match read: unset, emptied and "0" all mean "not required".
_REQUIRE_ENV = "CONTRACT_REQUIRE_MODEL_ARMOR_SDK"
_REQUIRED = os.environ.get(_REQUIRE_ENV) == "1"

try:
    from google.api_core import exceptions as api_exceptions
    from google.cloud import modelarmor_v1
except ImportError as exc:  # pragma: no cover - exercised by whichever gate lacks the extra
    if _REQUIRED:
        raise RuntimeError(
            f"{_REQUIRE_ENV}=1 but google-cloud-modelarmor is not importable, so the Model "
            "Armor mapping would have SKIPPED in a gate that exists to run it. Install the "
            "runtime lockfile (pip install -r requirements-gcp.lock) or stop setting the flag."
        ) from exc
    pytest.skip(
        f"google-cloud-modelarmor is not installed (the SDK-free gate). Set {_REQUIRE_ENV}=1 "
        "where the runtime lockfile is installed to make this a hard failure instead.",
        allow_module_level=True,
    )

_STATE = modelarmor_v1.FilterMatchState
_INVOCATION = modelarmor_v1.InvocationResult
_TEXT = "Acme (FICTIONAL): a routine note"


def _result(state: Any, invocation: Any, *, skipped: bool = False) -> Any:
    """A real SanitizationResult; ``skipped`` adds the PI/jailbreak filter as not having run."""
    filter_results = {}
    if skipped:
        filter_results["pi_and_jailbreak"] = modelarmor_v1.FilterResult(
            pi_and_jailbreak_filter_result=modelarmor_v1.PiAndJailbreakFilterResult(
                execution_state=modelarmor_v1.FilterExecutionState.EXECUTION_SKIPPED,
                match_state=_STATE.NO_MATCH_FOUND,
            )
        )
    return modelarmor_v1.SanitizationResult(
        filter_match_state=state, invocation_result=invocation, filter_results=filter_results
    )


def _prompt_response(
    state: Any | None, invocation: Any = _INVOCATION.SUCCESS, *, skipped: bool = False
) -> Any:
    if state is None:
        return modelarmor_v1.SanitizeUserPromptResponse()
    return modelarmor_v1.SanitizeUserPromptResponse(
        sanitization_result=_result(state, invocation, skipped=skipped)
    )


def _model_response(state: Any, invocation: Any = _INVOCATION.SUCCESS) -> Any:
    return modelarmor_v1.SanitizeModelResponseResponse(
        sanitization_result=_result(state, invocation)
    )


class _RecordingClient:
    """Stands in for the transport only: records each request, answers a real message."""

    def __init__(
        self,
        state: Any | None = None,
        *,
        invocation: Any = _INVOCATION.SUCCESS,
        error: Exception | None = None,
    ) -> None:
        self.state = state
        self.invocation = invocation
        self.error = error
        self.calls: list[tuple[str, Any, Any]] = []

    def sanitize_user_prompt(self, *, request: Any, timeout: Any = None) -> Any:
        self.calls.append(("sanitize_user_prompt", request, timeout))
        if self.error is not None:
            raise self.error
        return _prompt_response(self.state, self.invocation)

    def sanitize_model_response(self, *, request: Any, timeout: Any = None) -> Any:
        self.calls.append(("sanitize_model_response", request, timeout))
        if self.error is not None:
            raise self.error
        return _model_response(self.state, self.invocation)


def _adapter(client: _RecordingClient) -> ModelArmorGuardrailAdapter:
    return ModelArmorGuardrailAdapter(local_settings(profile="gcp"), client=client)


# --------------------------------------------------------------------------- #
# The defect this module exists for, stated against the real enum
# --------------------------------------------------------------------------- #
def test_str_of_the_real_enum_does_not_carry_its_name() -> None:
    """Why the adapter reads ``.name``: a substring test over ``str()`` can never match."""
    assert "MATCH_FOUND" not in str(_STATE.MATCH_FOUND)
    assert _STATE.MATCH_FOUND.name == "MATCH_FOUND"


@pytest.mark.parametrize(
    ("mirror", "real"),
    [
        (model_armor_enums.FilterMatchState, _STATE),
        (model_armor_enums.InvocationResult, _INVOCATION),
    ],
    ids=["FilterMatchState", "InvocationResult"],
)
def test_the_sdk_free_mirrors_match_the_real_enums(mirror: Any, real: Any) -> None:
    """The SDK-free half proves the mapping against these mirrors; they may not drift."""
    assert {m.name: int(m) for m in mirror} == {m.name: int(m) for m in real}


# --------------------------------------------------------------------------- #
# The mapping: allowed ONLY on an explicit NO_MATCH_FOUND
# --------------------------------------------------------------------------- #
def test_match_found_blocks() -> None:
    verdict = ModelArmorGuardrailAdapter._map_result(
        _prompt_response(_STATE.MATCH_FOUND), Direction.INPUT, _TEXT
    )
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert verdict.reason == "blocked by Model Armor"
    assert verdict.findings


def test_no_match_found_allows_the_text_unchanged() -> None:
    verdict = ModelArmorGuardrailAdapter._map_result(
        _prompt_response(_STATE.NO_MATCH_FOUND), Direction.INPUT, _TEXT
    )
    assert verdict.allowed is True
    assert verdict.sanitized_text == _TEXT
    assert verdict.findings == ()


@pytest.mark.parametrize(
    "invocation",
    [_INVOCATION.PARTIAL, _INVOCATION.FAILURE, _INVOCATION.INVOCATION_RESULT_UNSPECIFIED],
    ids=["PARTIAL", "FAILURE", "UNSPECIFIED"],
)
def test_no_match_from_a_screen_where_filters_did_not_run_blocks(invocation: Any) -> None:
    """The skipped-filter response a padded prompt produces: no match, because nothing ran.

    Model Armor sets ``invocation_result`` independently of the match state, and a filter
    that skipped (input past its token limit, an unsupported language, a detector error)
    reports ``EXECUTION_SKIPPED`` with ``NO_MATCH_FOUND``.
    """
    verdict = ModelArmorGuardrailAdapter._map_result(
        _prompt_response(_STATE.NO_MATCH_FOUND, invocation, skipped=True), Direction.INPUT, _TEXT
    )
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no complete filter decision" in verdict.reason


def test_an_incomplete_output_screen_blocks_through_screen() -> None:
    client = _RecordingClient(_STATE.NO_MATCH_FOUND, invocation=_INVOCATION.PARTIAL)
    verdict = _adapter(client).screen(_TEXT, Direction.OUTPUT)
    assert verdict.allowed is False
    assert [call[0] for call in client.calls] == ["sanitize_model_response"]


@pytest.mark.parametrize(
    "response",
    [
        _prompt_response(None),  # no sanitization_result at all: an empty message comes back
        _prompt_response(_STATE.FILTER_MATCH_STATE_UNSPECIFIED),
        None,  # nothing came back
    ],
    ids=["missing-result", "unspecified-state", "no-response"],
)
def test_a_missing_or_undecided_result_blocks(response: Any) -> None:
    verdict = ModelArmorGuardrailAdapter._map_result(response, Direction.INPUT, _TEXT)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no filter decision" in verdict.reason


# --------------------------------------------------------------------------- #
# The call: the real request types, the template path, the deadline, in each direction
# --------------------------------------------------------------------------- #
def test_input_is_sent_as_a_user_prompt_with_the_deadline() -> None:
    client = _RecordingClient(_STATE.NO_MATCH_FOUND)
    adapter = _adapter(client)
    verdict = adapter.screen(_TEXT, Direction.INPUT)
    assert verdict.allowed is True
    [(method, request, timeout)] = client.calls
    assert method == "sanitize_user_prompt"
    assert isinstance(request, modelarmor_v1.SanitizeUserPromptRequest)
    assert request.user_prompt_data.text == _TEXT
    assert request.name.endswith("/templates/" + local_settings().model_armor.template_id)
    assert timeout == local_settings().model_armor.timeout_seconds
    assert timeout > 0


def test_output_is_sent_as_a_model_response_and_a_match_blocks() -> None:
    client = _RecordingClient(_STATE.MATCH_FOUND)
    verdict = _adapter(client).screen(_TEXT, Direction.OUTPUT)
    assert verdict.allowed is False
    [(method, request, timeout)] = client.calls
    assert method == "sanitize_model_response"
    assert isinstance(request, modelarmor_v1.SanitizeModelResponseRequest)
    assert request.model_response_data.text == _TEXT
    assert timeout == local_settings().model_armor.timeout_seconds


@pytest.mark.parametrize(
    "error",
    [
        api_exceptions.DeadlineExceeded("deadline"),
        api_exceptions.ServiceUnavailable("unavailable"),
        api_exceptions.PermissionDenied("denied"),
    ],
    ids=["deadline", "unavailable", "denied"],
)
def test_an_api_error_propagates_rather_than_allowing(error: Exception) -> None:
    with pytest.raises(type(error)):
        _adapter(_RecordingClient(error=error)).screen(_TEXT, Direction.INPUT)


# --------------------------------------------------------------------------- #
# End to end through the domain, on the managed adapter
# --------------------------------------------------------------------------- #
def _service(client: _RecordingClient) -> tuple[TriageService, Any]:
    from contract_obligation_extraction.config import build_container

    container = build_container(local_settings())
    return TriageService(container.audit, container.tracer, _adapter(client)), container


def test_a_match_refuses_the_triage_and_audits_it() -> None:
    service, container = _service(_RecordingClient(_STATE.MATCH_FOUND))
    with pytest.raises(GuardrailBlockedError, match="Model Armor"):
        service.triage(TriageInput("Acme (FICTIONAL)", "routine note"), actor="a")
    record = container.audit.log.read_all()[-1]
    assert record["decision"] == Decision.BLOCKED.value
    assert record["severity"] is None


def test_an_api_error_refuses_the_triage_and_audits_it() -> None:
    service, container = _service(
        _RecordingClient(error=api_exceptions.DeadlineExceeded("deadline"))
    )
    with pytest.raises(api_exceptions.DeadlineExceeded):
        service.triage(TriageInput("Acme (FICTIONAL)", "routine note"), actor="a")
    record = container.audit.log.read_all()[-1]
    assert record["decision"] == Decision.BLOCKED.value
    assert "guardrail unavailable (DeadlineExceeded)" in record["redacted_summary"]


def test_no_match_in_both_directions_triages_normally() -> None:
    client = _RecordingClient(_STATE.NO_MATCH_FOUND)
    service, _ = _service(client)
    result = service.triage(TriageInput("Acme (FICTIONAL)", "routine note"), actor="a")
    assert result.summary == "Acme (FICTIONAL): triaged low"
    # The subject, the text, then the two joined as the generation step's prompt; then OUTPUT.
    assert [call[0] for call in client.calls] == [
        "sanitize_user_prompt",
        "sanitize_user_prompt",
        "sanitize_user_prompt",
        "sanitize_model_response",
    ]
