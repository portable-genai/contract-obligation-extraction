"""Local GenerationPort: a deterministic, SDK-free narrator for the offline profile.

It stands in for a managed model in the gate, the tests and the demo. It never decides anything:
it restates the engine-owned register facts it is handed as a short JSON note, so its output is
grounded by construction and the whole offline pipeline (including the narration path) runs with
no network and no cloud SDK. A silent empty return would let a producer ship the narration seam
unwired, so this deliberately produces a real, inspectable note.
"""

from __future__ import annotations

import json

from hex_service_kit import provenance

from ...config import Settings
from ...ports.generation import GenerationRequest, GenerationResponse

#: What the console's model pill names when this stub answers: the same string
#: ``Settings.generator_model`` reports under ``local``, so the pill never changes its story
#: between "configured" and "answered" on a laptop.
STUB_MODEL = "deterministic-offline-stub"


class LocalGenerationAdapter:
    """Restate the request's engine facts as a deterministic JSON note (no model, no network)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        values = dict(request.facts)
        note = (
            f"Register carries {values.get('obligations', '0')} obligations, "
            f"{values.get('flagged', '0')} flagged and {values.get('needs_review', '0')} needing "
            f"review; {values.get('overdue', '0')} deadline(s) overdue and "
            f"{values.get('in_notice_window', '0')} inside a notice window."
        )
        provenance.note_model(STUB_MODEL)
        return GenerationResponse(text=json.dumps({"note": note}), model="local-deterministic")
