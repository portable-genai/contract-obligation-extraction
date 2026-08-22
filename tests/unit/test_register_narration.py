"""Register narration: grounded output is kept, a hallucinated figure is discarded not repaired.

The model narrates the register's figures and never produces them. These prove the two hard rules
the service enforces: schema-invalid or ungrounded output is dropped for the deterministic
fallback (which is grounded by construction), and the fallback still carries the engine's numbers.
"""

from __future__ import annotations

from contract_obligation_extraction.adapters.local.audit import LocalAuditAdapter
from contract_obligation_extraction.config import Settings
from contract_obligation_extraction.domain.contracts import RegisterService
from contract_obligation_extraction.domain.corpus import AS_OF, contract_by_id, proposals_for
from contract_obligation_extraction.domain.narration import (
    NarrationService,
    build_request,
    note_is_grounded,
    parse_note,
)
from contract_obligation_extraction.ports.generation import (
    GenerationPort,
    GenerationRequest,
    GenerationResponse,
)


class _Hallucinator:
    """A model that invents a figure the engine never produced."""

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(text='{"note": "the register has 4242 overdue deadlines"}')


class _Malformed:
    """A model that returns non-JSON."""

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        return GenerationResponse(text="not json at all")


def _register(contract_id: str):
    contract = contract_by_id(contract_id)
    assert contract is not None
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    return RegisterService(audit).build(
        contract, proposals_for(contract_id), as_of=AS_OF, actor="bot"
    )


def test_a_grounded_model_note_is_kept() -> None:
    reg = _register("meridian-msa-2026")
    port: GenerationPort = LocalGenerationAdapterFactory()
    note = NarrationService(port).narrate(reg)
    assert note.grounded is True
    assert note_is_grounded(note.text, build_request(reg).facts)


def test_a_hallucinated_figure_is_discarded_for_the_grounded_fallback() -> None:
    reg = _register("apex-outsourcing-2026")
    note = NarrationService(_Hallucinator()).narrate(reg)
    assert note.model_authored is False
    assert "4242" not in note.text
    assert note_is_grounded(note.text, build_request(reg).facts)


def test_malformed_model_output_falls_back_and_stays_grounded() -> None:
    reg = _register("meridian-dpa-2026")
    note = NarrationService(_Malformed()).narrate(reg)
    assert note.model_authored is False
    assert note.grounded is True
    assert parse_note("not json") is None


def LocalGenerationAdapterFactory() -> GenerationPort:
    from contract_obligation_extraction.adapters.local.generation import LocalGenerationAdapter

    return LocalGenerationAdapter(Settings(profile="local"))
