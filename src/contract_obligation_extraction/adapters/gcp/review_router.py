"""Managed ReviewRouterPort: submit the routed review to Hrz7 via ``review-kit``.

Builds the review from the escalated result and submits it to the Hrz7 service intake
(``POST /v1/service/reviews``), authenticated as a trusted service caller. The console base URL
comes from ``review_url`` in ``config/settings.yaml`` (default ``${HUMAN_REVIEW_URL:-}``,
the workspace-wide name the other producers use) and the credentials from
``HUMAN_REVIEW_S2S_TOKEN`` / ``HUMAN_REVIEW_S2S_SIGNING_KEY``, the OUTBOUND pair, deliberately
distinct from this service's own inbound ``CONTRACT_S2S_TOKEN``.

No cloud SDK is involved: the kit is pure stdlib ``urllib`` with S2S headers wire-compatible
with ``hex-service-kit``'s server verifier, so this module imports cleanly with no GCP SDK
present. It is bound in the managed profile because it makes a real network call to a sibling
service.
"""

from __future__ import annotations

from review_kit import ReviewClient

from ...config import Settings
from ...domain.models import TriageResult
from .._review_payload import result_to_review

_SERVICE_ACTOR = "contract-obligation-extraction"


class CloudReviewRouter:
    """Submit escalated results to Hrz7 (rule R8) through the shared submission client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def route(self, result: TriageResult, *, maker: str, tenant: str = "") -> str:
        base_url = self._settings.review_url.strip()
        if not base_url:
            # Fail closed: an escalation with nowhere to go must not be swallowed, because the
            # caller would then treat a routed-nowhere result as reviewed.
            raise RuntimeError(
                "review_url is not configured, so rule R8 cannot be honoured. Set "
                "HUMAN_REVIEW_URL (config/settings.yaml review_url) to the Hrz7 console."
            )
        # Constructed per call so a credential rotated or cleared after start-up is seen; the
        # client refuses a plaintext non-loopback URL and a missing bearer at construction.
        client = ReviewClient(
            base_url,
            token_env="HUMAN_REVIEW_S2S_TOKEN",
            signing_key_env="HUMAN_REVIEW_S2S_SIGNING_KEY",
        )
        review = result_to_review(result, maker=maker, tenant=tenant or self._settings.tenant)
        return client.submit(review, actor=_SERVICE_ACTOR).review_id
