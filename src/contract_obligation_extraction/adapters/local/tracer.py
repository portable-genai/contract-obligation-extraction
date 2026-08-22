"""Local ObservabilityTracerPort: a no-op that still records cost, SDK-free.

The offline profile has no trace backend and must not need one, so spans are a null context. Token
usage is kept in memory rather than discarded: the demo and the tests assert on it, which is what
stops the cost-reporting call sites from rotting unnoticed between deployments.

Nothing here captures content, and that is a property of the port rather than of this adapter
(principle P-04). See ``hex_service_kit.observability``.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext

from hex_service_kit.observability import TokenUsage

from ...config import Settings


class LocalNoopTracerAdapter:
    """Satisfies the tracer port with no exporter, no SDK and no network."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        #: Every ``(usage, model)`` reported this process, in call order.
        self.token_usage: list[tuple[TokenUsage, str]] = []

    def span(self, name: str, **attributes: str) -> AbstractContextManager[None]:
        return nullcontext()

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        self.token_usage.append((usage, model))
