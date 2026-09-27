"""The Model Armor verdict mapping, proved WITHOUT the SDK, so it runs in every gate.

``tests/unit/test_model_armor_mapping.py`` drives the real ``modelarmor_v1`` types, and skips
where the SDK is absent. The SDK-free ``make gate`` is what CI runs on a rendered repo, so that
module alone left the one line that decides whether anything is ever blocked unproved there:
putting a ``str()`` substring test back into ``_map_result`` kept every required check green.

This module feeds the mapping stdlib ``IntEnum`` mirrors of the two enums it reads
(``tests/fixtures/model_armor_enums.py``). Their ``str()`` is the member's number, as the real
enums' is, so the regression fails here. The SDK module pins the mirrors to the real enums.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any

import pytest

from contract_obligation_extraction.adapters.gcp.guardrail import (
    ModelArmorGuardrailAdapter,
)
from contract_obligation_extraction.domain.kernel import Direction

from tests.fixtures.model_armor_enums import FilterMatchState, InvocationResult

_TEXT = "Acme (FICTIONAL): a routine note"
_DIRECTIONS = [Direction.INPUT, Direction.OUTPUT]


def _response(state: Any, invocation: Any = InvocationResult.SUCCESS) -> SimpleNamespace:
    return SimpleNamespace(
        sanitization_result=SimpleNamespace(filter_match_state=state, invocation_result=invocation)
    )


def _map(response: Any, direction: Direction = Direction.INPUT) -> Any:
    return ModelArmorGuardrailAdapter._map_result(response, direction, _TEXT)


def test_the_mirror_str_is_the_number_not_the_name() -> None:
    """The premise: a ``str()`` substring test can see neither MATCH_FOUND nor SUCCESS."""
    assert "MATCH_FOUND" not in str(FilterMatchState.MATCH_FOUND)
    assert "SUCCESS" not in str(InvocationResult.SUCCESS)


@pytest.mark.parametrize("direction", _DIRECTIONS)
def test_a_complete_clean_screen_allows_the_text_unchanged(direction: Direction) -> None:
    verdict = _map(_response(FilterMatchState.NO_MATCH_FOUND), direction)
    assert verdict.allowed is True
    assert verdict.sanitized_text == _TEXT
    assert verdict.findings == ()


@pytest.mark.parametrize("direction", _DIRECTIONS)
@pytest.mark.parametrize("invocation", list(InvocationResult), ids=lambda m: m.name)
def test_a_match_blocks_however_many_filters_ran(
    direction: Direction, invocation: InvocationResult
) -> None:
    verdict = _map(_response(FilterMatchState.MATCH_FOUND, invocation), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert verdict.reason == "blocked by Model Armor"


@pytest.mark.parametrize("direction", _DIRECTIONS)
@pytest.mark.parametrize(
    "invocation",
    [
        InvocationResult.PARTIAL,
        InvocationResult.FAILURE,
        InvocationResult.INVOCATION_RESULT_UNSPECIFIED,
        None,
    ],
    ids=["PARTIAL", "FAILURE", "UNSPECIFIED", "absent"],
)
def test_no_match_from_an_incomplete_screen_blocks(
    direction: Direction, invocation: InvocationResult | None
) -> None:
    """A skipped filter reports no match. That is not a pass: the text was not screened."""
    verdict = _map(_response(FilterMatchState.NO_MATCH_FOUND, invocation), direction)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no complete filter decision" in verdict.reason
    assert verdict.findings and "not every filter ran" in verdict.findings[0].detail


@pytest.mark.parametrize(
    "response",
    [
        _response(FilterMatchState.FILTER_MATCH_STATE_UNSPECIFIED),
        SimpleNamespace(sanitization_result=None),
        SimpleNamespace(sanitization_result=SimpleNamespace()),
        object(),
        None,
    ],
    ids=["unspecified-state", "none-result", "empty-result", "no-result-attr", "no-response"],
)
def test_no_decision_blocks(response: Any) -> None:
    verdict = _map(response)
    assert verdict.allowed is False
    assert verdict.sanitized_text is None
    assert "no filter decision" in verdict.reason


def test_exactly_one_combination_of_the_two_enums_allows() -> None:
    allowed = [
        (state.name, invocation.name)
        for state, invocation in itertools.product(FilterMatchState, InvocationResult)
        if _map(_response(state, invocation)).allowed
    ]
    assert allowed == [("NO_MATCH_FOUND", "SUCCESS")]
