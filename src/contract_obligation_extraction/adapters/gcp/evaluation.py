"""Managed EvaluationGatePort: the Hrz4 promotion authority over HTTP.

Hrz4 owns the promotion verdict for the whole catalog (it is the E1/E2 gate owner), so this
adapter asks rather than decides. It carries no thresholds of its own: a repo that scored itself
and promoted itself would be a gate in name only.

The client comes from ``agent-eval-kit`` so the wire contract is shared with every other repo, and
it is constructed lazily because building a container must not require the quality service to be
reachable.
"""

from __future__ import annotations

from agent_eval_kit import EvalReport, PromotionGateClient
from hex_service_kit.netdefaults import ConfiguredEmptyError, read_env_setting

from ...config import Settings

#: Bundle name Hrz4 selects this repo's registered metric set by. A rendered value, so it lives
#: in a module constant: inline it would make the line length depend on the project slug.
_BUNDLE = "contract-obligation-extraction"
_QUALITY_URL_ENV = "CONTRACT_QUALITY_URL"
_DEFAULT_QUALITY_URL = "http://localhost:8084"
#: The model the verdict is recorded AGAINST. Hrz4 keys a promotion to the exact model and
#: prompt version that produced the evidence, so a model swap invalidates the old verdict
#: rather than inheriting it. Change this in the same commit that changes the model.
_GATED_MODEL = "gemini-3.5-flash"


class ManagedEvalGateAdapter:
    """Delegates evaluation and promotion to the Hrz4 AI-quality service."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: PromotionGateClient | None = None

    def _gate_client(self) -> PromotionGateClient:
        if self._client is None:
            # Three states, because this names WHERE the promotion authority is. Unset takes the
            # documented default. EMPTIED names no authority at all, and a gate with no authority
            # must refuse rather than quietly fall back to a default the operator just removed.
            setting = read_env_setting(_QUALITY_URL_ENV)
            if setting.is_configured_empty:
                raise ConfiguredEmptyError(
                    f"{_QUALITY_URL_ENV} is set but empty, so no promotion authority is named. "
                    f"Unset it to use {_DEFAULT_QUALITY_URL}, or give it the Hrz4 service URL."
                )
            url = setting.value or _DEFAULT_QUALITY_URL
            self._client = PromotionGateClient(url, bundle=_BUNDLE, model=_GATED_MODEL)
        return self._client

    def evaluate(self, dataset_path: str) -> EvalReport:
        return self._gate_client().evaluate(dataset_path)

    def gate(self, target: str) -> bool:
        return self._gate_client().gate(target)
