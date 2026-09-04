"""Managed ObservabilityTracerPort: OpenTelemetry, built by the commons.

This adapter is deliberately thin. All the OpenTelemetry work lives in ``hex_service_kit.tracing``
(the ``otel`` extra), so the exporter choice, the Cloud Run authentication the agent-observability
collector requires, and the rule that a tracing fault never becomes a request fault are implemented
once for the whole fleet rather than per repo.

Where spans go is a DEPLOYMENT fact, not a code fact, and it is read from
``OTEL_EXPORTER_OTLP_ENDPOINT``: set, they go OTLP to the agent-observability collector, which
redacts and aggregates; unset, straight to Cloud Trace. Both are supported, so this is one adapter
and not two profiles.

The commons import is lazy for the usual reason (practice A5): the local and on-prem profiles
import this package with no cloud SDK installed, and ``hex_service_kit.tracing`` itself imports
clean without OpenTelemetry, but the extra may simply not be present.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

from hex_service_kit.observability import ObservabilityTracerPort, TokenUsage

from ...config import Settings

#: The service name every span is attributed to in the trace backend and the topology view.
#: A module constant because it holds a RENDERED value: inline in the call below, a long
#: project slug would push the line past the limit and `ruff format` cannot wrap a literal.
_SERVICE_NAME = "contract-obligation-extraction"


class CloudTracerAdapter:
    """Binds the tracer port to the commons OpenTelemetry implementation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._delegate: ObservabilityTracerPort | None = None

    def _tracer(self) -> ObservabilityTracerPort:
        if self._delegate is None:
            from hex_service_kit.tracing import build_tracer  # noqa: PLC0415

            self._delegate = build_tracer(
                service=_SERVICE_NAME,
                project=self._settings.project_id,
            )
        return self._delegate

    def span(self, name: str, **attributes: str) -> AbstractContextManager[None]:
        return self._tracer().span(name, **attributes)

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        self._tracer().record_token_usage(usage, model)
