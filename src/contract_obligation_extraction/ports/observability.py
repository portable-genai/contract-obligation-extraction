"""The observability boundaries, re-exported rather than redeclared.

Neither Protocol is written out here. ``ObservabilityTracerPort`` and ``TokenUsage`` come from
``hex-service-kit`` and ``EvaluationGatePort`` from ``agent-eval-kit``, for the same reason
``IdentityPort`` does in :mod:`.` : sixteen repositories each hand-copied these and they had
already drifted apart. One had dropped the evaluation port entirely, two had dropped its ``gate``
method and kept only ``evaluate``, and one returned ``str`` from an audit ``record`` that returns
``None`` everywhere else. A Protocol copied into N repositories is N Protocols, and only one of
them gets fixed when a defect is found.

The two ports are split across the two commons packages by where their types already live: the
tracer beside the value type it reports, the gate beside the ``EvalReport`` it returns. Both are
typing-only imports, so this module costs the offline profile nothing: no OpenTelemetry, no HTTP
client, no cloud SDK. The OpenTelemetry implementation is in ``hex_service_kit.tracing`` behind
the ``otel`` extra and is reached only by the ``gcp`` adapter.
"""

from __future__ import annotations

from agent_eval_kit import EvaluationGatePort
from hex_service_kit.observability import ObservabilityTracerPort, TokenUsage

__all__ = [
    "EvaluationGatePort",
    "ObservabilityTracerPort",
    "TokenUsage",
]
