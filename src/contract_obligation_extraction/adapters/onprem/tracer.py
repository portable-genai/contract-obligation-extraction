"""On-prem ObservabilityTracerPort: absent, deliberately NOT fail-fast.

Every other on-prem placeholder in this repo raises, because an audit sink or a guardrail that
silently does nothing is a control that has been removed. Tracing is different: it is not
essential to correctness and it carries no compliance claim, so an on-prem deployment with no
trace backend should run normally rather than refuse to start.

Making this one raise would have forced every on-prem operator to bind a tracing stack before the
service would serve a request, which is a portability barrier invented for a diagnostic. A client
who wants traces binds an exporter here; a client who does not, does nothing.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext

from hex_service_kit.observability import TokenUsage

from ...config import Settings


class OnPremTracerAdapter:
    """Satisfies the tracer port and records nothing."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def span(self, name: str, **attributes: str) -> AbstractContextManager[None]:
        return nullcontext()

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        return None
