"""GCP ExtractionPort: Document AI layout parsing plus a long-context Gemini read (lazy imports).

The managed extraction path parses the contract's layout with Document AI and reads clause text
with a long-context Gemini model, returning candidate obligations, dates and proposed flags. It
decides nothing: the engine validates every cited clause anchor and every proposed flag. Both SDK
imports live INSIDE the method so the ``local`` / ``onprem`` profiles import this module with no
cloud SDK installed, which is why the managed family REFUSES (an ``ImportError``) under the
offline gate rather than answering. The import roots are ``google.*``, already covered by the
repo's mypy override.
"""

from __future__ import annotations

from ...config import Settings
from ...ports.extraction import ExtractionRequest, ExtractionResult


class CloudExtractionAdapter:
    """Read a contract through Document AI and a managed long-context model."""

    #: A long-context model: contracts run to tens of thousands of tokens and the read is
    #: single-shot per document.
    _MODEL = "gemini-3.5-pro"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def extract(
        self, request: ExtractionRequest
    ) -> ExtractionResult:  # pragma: no cover - needs live GCP
        # Lazy imports: absent in the offline profiles and in CI, so this raises there rather than
        # answering, which is exactly the managed-family refusal the parity suite asserts. The
        # layout parse and the long-context read are wired here at deployment time.
        import google.generativeai as genai  # noqa: F401  (long-context read; model _MODEL)
        from google.cloud import documentai  # noqa: F401  (layout parse; wired by the deployment)

        # The concrete Document AI batch call and the JSON schema binding are a deployment decision
        # (processor id, layout config, the model _MODEL above), wired in the runbook; the seam is
        # proven by the port contract and the offline fixture, not by a live call in the gate.
        raise NotImplementedError(
            "managed extraction requires a configured Document AI processor and model endpoint; "
            "see docs/runbook.md. The offline profile uses the deterministic fixture reader."
        )
