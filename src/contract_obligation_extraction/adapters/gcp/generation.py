"""GCP GenerationPort: Gemini narration (SDK imports stay lazy).

The model is used for narration only; the consequential numbers are computed by the deterministic
engine and merely restated here. The Gemini SDK import lives INSIDE the method so the
``local``/``onprem`` profiles import this module with no cloud SDK installed (the portability
proof, and the reason the managed family refuses rather than succeeds under the offline gate). The
import root is ``google.*``, which the repo's mypy override already covers.

The SDK is ``google-genai``, the unified Google GenAI SDK. It replaced ``google-generativeai``,
which is RETIRED; this module used the retired one until 2026-08-31 and the migration was not a
pin bump, because the call shape differs: a stateful ``GenerativeModel`` holding the system
instruction became a client plus a per-call ``GenerateContentConfig`` that carries it. The client
is constructed with no arguments on purpose, which is what the retired SDK also did: credentials
and backend come from the environment, so a deployment can send this at either the Gemini
Developer API or Vertex (``GOOGLE_GENAI_USE_VERTEXAI``) without a code change here.
"""

from __future__ import annotations

from ...config import Settings
from ...ports.generation import GenerationRequest, GenerationResponse


class CloudGenerationAdapter:
    """Narrate through a managed Gemini model."""

    #: The narration model. A cheap, fast model is right: this path produces prose, never a number.
    _MODEL = "gemini-3.5-flash"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(
        self, request: GenerationRequest
    ) -> GenerationResponse:  # pragma: no cover - needs live GCP
        # Lazy import: absent in the offline profiles and in CI, so this raises there rather than
        # answering, which is exactly the managed-family refusal the parity suite asserts.
        from google import genai
        from google.genai import types

        client = genai.Client()
        completion = client.models.generate_content(
            model=self._MODEL,
            contents=request.prompt,
            config=types.GenerateContentConfig(
                system_instruction=request.system,
                response_mime_type="application/json",
                max_output_tokens=request.max_output_tokens,
                temperature=0.2,
            ),
        )
        return GenerationResponse(text=completion.text or "", model=self._MODEL)
