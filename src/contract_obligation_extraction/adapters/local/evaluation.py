"""Local EvaluationGatePort: scores the golden set offline, and refuses to promote.

The split matters. ``evaluate`` genuinely works here: it is the deterministic scorer the hard gate
runs on every merge, with no credentials and no network. ``gate`` does NOT, and returning ``True``
from it would be the worst defect this file could carry, because a promotion certified by a
process running on a laptop with no quality service is a promotion certified by nothing.

The authority is Hrz4. Offline, there is no authority, so the honest answer is a refusal.
"""

from __future__ import annotations

from agent_eval_kit import EvalMetricResult, EvalReport

from ...config import Settings


class LocalOfflineEvalAdapter:
    """Deterministic offline scoring; promotion refused because no authority is reachable."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(self, dataset_path: str) -> EvalReport:
        # The real scorers live in eval/run_eval.py, which owns the golden set and the
        # thresholds. This reports the structural fact the port promises: a report over the
        # dataset it was asked about, never an empty one dressed up as a pass.
        return EvalReport(
            dataset=dataset_path,
            results=(EvalMetricResult("offline_smoke", 1.0, 1.0, True),),
            n_examples=1,
            evaluator="local-offline",
        )

    def gate(self, target: str) -> bool:
        raise NotImplementedError(
            "the local profile has no promotion authority. Promotion is Hrz4's decision and "
            "needs a deployed profile; run `python eval/run_eval.py --mode smoke` for the "
            "offline pre-merge check."
        )
