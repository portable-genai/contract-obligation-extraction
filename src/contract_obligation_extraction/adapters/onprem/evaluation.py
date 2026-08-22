"""On-prem EvaluationGatePort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

Unlike the on-prem tracer, which is absent rather than fatal, this one raises. Tracing is a
diagnostic and a client may reasonably run without it; a promotion gate is a control, and a client
running without one must find that out at the call rather than discover later that everything was
promoted unchecked.
"""

from __future__ import annotations

from agent_eval_kit import EvalReport

from ...config import Settings


class OnPremEvalAdapter:
    """Satisfies the port but refuses at call time: the client wires its own quality authority."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, dataset_path: str) -> EvalReport:
        raise NotImplementedError(
            "on-prem evaluation is a portability placeholder: bind the client's own quality "
            "service (see docs/onprem-migration.md)"
        )

    def gate(self, target: str) -> bool:
        raise NotImplementedError(
            "on-prem promotion gate is a portability placeholder: bind the client's own quality "
            "authority (see docs/onprem-migration.md)"
        )
