"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

The Gemini adapter is driven here through a FAKE ``google.genai`` module, so what is proved is
this repository's half: the model id the call notes, and the sampling it sends. The one model
call site, the register narration, is drafting, so it is FREE: no temperature at all.
"""

from __future__ import annotations

import dataclasses
import sys
import types
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

from contract_obligation_extraction import config
from contract_obligation_extraction.adapters.gcp.generation import CloudGenerationAdapter
from contract_obligation_extraction.adapters.local.generation import (
    STUB_MODEL,
    LocalGenerationAdapter,
)
from contract_obligation_extraction.ports.generation import GenerationRequest, GenerationResponse

from tests import REPO_ROOT
from tests.conftest import LOOPBACK_PEER, local_settings, reimport

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"
_AUDITOR = {"X-Dev-Persona": "auditor"}


@pytest.fixture()
def api_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A fresh app under ``local``, whatever the shell exported (CI exports nothing)."""
    monkeypatch.setenv("CONTRACT_PROFILE", "local")
    module = reimport("contract_obligation_extraction.api.app")
    with TestClient(module.app, client=LOOPBACK_PEER) as client:
        yield client


def _register(api_client: TestClient) -> dict[str, str]:
    response = api_client.post(
        "/v1/register", json={"contract_id": "apex-outsourcing-2026"}, headers=_AUDITOR
    )
    assert response.status_code == 200, response.text
    return dict(response.headers)


def test_the_local_stub_answers_as_the_model_the_pill_first_names(
    api_client: TestClient,
) -> None:
    """Under ``local`` the pill before and after the answer name the same stub."""
    headers = _register(api_client)
    assert headers[ANSWERED_BY] == STUB_MODEL
    assert local_settings().generator_model == STUB_MODEL
    assert SEARCH_USED not in headers


def test_a_request_that_noted_nothing_sends_neither_header(api_client: TestClient) -> None:
    response = api_client.get("/healthz")
    assert response.status_code == 200
    assert ANSWERED_BY not in response.headers
    assert SEARCH_USED not in response.headers


def test_a_call_that_searched_says_so_and_the_next_request_starts_fresh(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = LocalGenerationAdapter.generate

    def searching(self: LocalGenerationAdapter, request: GenerationRequest) -> GenerationResponse:
        provenance.note_model("fake-searching-model")
        provenance.note_search()
        return original(self, request)

    monkeypatch.setattr(LocalGenerationAdapter, "generate", searching)
    headers = _register(api_client)
    assert "fake-searching-model" in headers[ANSWERED_BY].split(", ")
    assert headers[SEARCH_USED] == "true"
    monkeypatch.setattr(LocalGenerationAdapter, "generate", original)
    headers = _register(api_client)
    assert headers[ANSWERED_BY] == STUB_MODEL
    assert SEARCH_USED not in headers


def _narration_request(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> GenerationRequest:
    """The request the register route's narration call site actually sends."""
    seen: list[GenerationRequest] = []
    original = LocalGenerationAdapter.generate

    def capture(self: LocalGenerationAdapter, request: GenerationRequest) -> GenerationResponse:
        seen.append(request)
        return original(self, request)

    monkeypatch.setattr(LocalGenerationAdapter, "generate", capture)
    _register(api_client)
    monkeypatch.setattr(LocalGenerationAdapter, "generate", original)
    assert seen, "the register route never narrated"
    return seen[0]


def test_the_narration_call_site_is_drafting_so_it_sends_no_temperature(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _narration_request(api_client, monkeypatch).temperature is None


# --------------------------------------------------------------------------------------- #
# The Gemini adapter, through a fake SDK.
# --------------------------------------------------------------------------------------- #
class _FakeModels:
    def __init__(self, text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._text = text

    def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self._text)


def _fake_genai(monkeypatch: pytest.MonkeyPatch, text: str) -> _FakeModels:
    models = _FakeModels(text)
    genai = types.ModuleType("google.genai")
    genai_types = types.ModuleType("google.genai.types")
    genai_types.GenerateContentConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    genai.types = genai_types  # type: ignore[attr-defined]
    genai.Client = lambda **_: SimpleNamespace(models=models)  # type: ignore[attr-defined]
    google = sys.modules.get("google") or types.ModuleType("google")
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
    return models


def _gcp_settings() -> config.Settings:
    return dataclasses.replace(local_settings(), profile="gcp")


def test_the_gemini_narrator_notes_its_model_and_drafts_with_no_temperature(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _narration_request(api_client, monkeypatch)
    models = _fake_genai(monkeypatch, '{"note": "A drafted note."}')
    settings = _gcp_settings()
    with provenance.scope() as record:
        CloudGenerationAdapter(settings).generate(request)
    assert record.models == [settings.generator_model]
    assert record.search_used is False, "no online search tool is attached to narration"
    (call,) = models.calls
    assert call["model"] == settings.generator_model
    assert "temperature" not in vars(call["config"]), "free sampling sends no temperature"
    assert "tools" not in vars(call["config"])


def test_a_pinned_request_reaches_the_gemini_config(monkeypatch: pytest.MonkeyPatch) -> None:
    models = _fake_genai(monkeypatch, "{}")
    pinned = GenerationRequest(system="s", prompt="p", temperature=0.0)
    CloudGenerationAdapter(_gcp_settings()).generate(pinned)
    assert models.calls[0]["config"].temperature == 0.0


# --------------------------------------------------------------------------------------- #
# generator_model is the model the adapter calls.
# --------------------------------------------------------------------------------------- #
def test_generator_model_is_the_model_the_gemini_adapter_calls() -> None:
    assert _gcp_settings().generator_model == CloudGenerationAdapter._MODEL  # noqa: SLF001


def test_no_flag_swaps_in_a_model_the_adapter_never_calls() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered."""
    models = SimpleNamespace(
        reasoning="the-model-the-adapter-calls",
        hard_reasoning="a-model-nobody-calls",
        use_hard_reasoning=True,
    )
    named = config._model_from_settings(SimpleNamespace(models=models), "models.reasoning")  # noqa: SLF001
    assert named == "the-model-the-adapter-calls"


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    settings_file = REPO_ROOT / "config" / "settings.yaml"
    assert "use_hard_reasoning" not in settings_file.read_text(encoding="utf-8")
    for source in sorted((REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
