"""On-prem ExtractionPort: fail-fast portability placeholder.

The client wires its own layout parser and in-VPC model behind this seam. Until then it refuses at
call time rather than pretending to read a contract, so a placeholder never becomes a silent
no-op on the one path where an empty answer would look like a contract that genuinely carries no
obligations.
"""

from __future__ import annotations

from ...config import Settings
from ...ports.extraction import ExtractionRequest, ExtractionResult


class OnPremExtractionAdapter:
    """Satisfies ExtractionPort but refuses at call time: the client binds its own reader."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        raise NotImplementedError(
            "on-prem extraction is a portability placeholder: bind the client's own contract "
            "parser and model endpoint (see docs/onprem-migration.md)"
        )
