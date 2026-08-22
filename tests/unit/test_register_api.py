"""The /v1/register surface: engine numbers, the Rgc8 feed, R8 routing, 403/404, and determinism.

The endpoint runs the deterministic engine, narrates through the bound model, routes any material
register to Hrz7 (rule R8) in the same request, and authorises the read against the VERIFIED
principal's tenant. The determinism proof is load-bearing: with the narrator replaced by a
hallucinating stub, every consequential field is byte-identical and the invented figures never
appear.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from contract_obligation_extraction.adapters.local.generation import LocalGenerationAdapter
from contract_obligation_extraction.ports.generation import GenerationRequest, GenerationResponse

from tests.conftest import LOOPBACK_PEER, reimport


@pytest.fixture()
def api_client() -> Iterator[TestClient]:
    """A FRESH local api.app, reimported under the ambient (local) profile.

    The IAP suite reimports ``api.app`` under the managed profile and leaves that module cached,
    so a test that merely `from ... import app`-ed would pick up a gcp-posture app whenever it ran
    after those. Reimporting here makes this suite's posture independent of test ordering.
    """
    module = reimport("contract_obligation_extraction.api.app")
    with TestClient(module.app, client=LOOPBACK_PEER) as client:
        yield client


_AUDITOR = {"X-Dev-Persona": "auditor"}  # tenant demo-bank: the contract owner
_OTHER_TENANT = {"X-Dev-Persona": "other-tenant"}  # tenant other-bank

_CONSEQUENTIAL = (
    "severity",
    "decision",
    "requires_human_review",
    "obligations",
    "dropped",
    "flag_counts",
    "feed",
)


def test_register_returns_engine_numbers_and_routes(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/register", json={"contract_id": "apex-outsourcing-2026"}, headers=_AUDITOR
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["severity"] == "high"
    assert body["requires_human_review"] is True
    assert body["review_ref"], "rule R8: a material register is ROUTED, not merely flagged"
    assert body["citations"] and body["note"]
    # The versioned Rgc8 feed rides along.
    assert body["feed"]["schema_version"]


def test_register_drops_an_uncited_candidate(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/register", json={"contract_id": "meridian-msa-2026"}, headers=_AUDITOR
    )
    body = resp.json()
    assert len(body["dropped"]) == 1
    assert all(row["clause_number"] != "9" for row in body["obligations"])


def test_a_clean_sow_does_not_escalate(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/register", json={"contract_id": "meridian-sow-014"}, headers=_AUDITOR
    )
    body = resp.json()
    assert body["severity"] == "low"
    assert body["requires_human_review"] is False
    assert body["review_ref"] == ""


def test_register_denies_a_cross_tenant_principal_with_403(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/register", json={"contract_id": "meridian-msa-2026"}, headers=_OTHER_TENANT
    )
    assert resp.status_code == 403  # not 404: the contract exists, the caller is not authorised


def test_register_unknown_contract_is_404(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/register", json={"contract_id": "no-such-contract"}, headers=_AUDITOR
    )
    assert resp.status_code == 404


def _hallucinate(self: LocalGenerationAdapter, request: GenerationRequest) -> GenerationResponse:
    """Stand in for a model that invents figures the engine never produced."""
    return GenerationResponse(
        text='{"note": "register carries 999 obligations, 888 flagged and 777 overdue"}',
        model="hallucinating-stub",
    )


def test_register_numbers_are_identical_when_generation_is_stubbed(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {"contract_id": "meridian-dpa-2026"}
    honest = api_client.post("/v1/register", json=body, headers=_AUDITOR).json()

    monkeypatch.setattr(LocalGenerationAdapter, "generate", _hallucinate)
    stubbed = api_client.post("/v1/register", json=body, headers=_AUDITOR).json()

    for field in _CONSEQUENTIAL:
        assert honest[field] == stubbed[field], f"{field} moved when only the model changed"
    # The hallucinated figures are discarded, never surfaced.
    for invented in ("999", "888", "777"):
        assert invented not in stubbed["note"]
