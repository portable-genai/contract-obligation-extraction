"""Local ExtractionPort: a deterministic, SDK-free contract reader for the offline profile.

It stands in for Document AI plus a long-context model in the gate, the tests and the demo. It
never decides anything: it replays the canned proposals the corpus carries for a known contract,
so the offline pipeline (segmentation, admission, flag validation, the renewal clock) runs end to
end with no network and no cloud SDK. A silent empty return would let a producer ship the
extraction seam unwired, so a known contract returns its real, inspectable proposals; an unknown
one returns an empty result, which is a fixture's honest answer, not a failure.
"""

from __future__ import annotations

from hex_service_kit import provenance

from ...config import Settings
from ...domain.corpus import proposals_for
from ...ports.extraction import ExtractionRequest, ExtractionResult
from .generation import STUB_MODEL


class LocalExtractionAdapter:
    """Replay the corpus's canned proposals for a contract (no model, no network)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        # It stands in for a model read, so the pill says a stub answered rather than nothing.
        provenance.note_model(STUB_MODEL)
        return proposals_for(request.contract_id)
