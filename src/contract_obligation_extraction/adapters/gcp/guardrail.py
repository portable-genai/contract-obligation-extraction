"""Managed GuardrailPort: Model Armor (rule R1).

Every inbound prompt and outbound response the domain narrates is screened via
``sanitizeUserPrompt`` / ``sanitizeModelResponse`` against a regional Model Armor template
(``config/settings.yaml`` ``model_armor.template_id``, on the regional host
``model_armor.host``, pinned for residency, P-05), with an explicit per-call deadline
(``model_armor.timeout_seconds``) so a stalled backend refuses the request instead of holding it.

FAIL CLOSED, in every place it can go wrong:

- the verdict is ALLOWED only when ``filter_match_state`` is ``NO_MATCH_FOUND`` AND
  ``invocation_result`` is ``SUCCESS``, each read by the enum member's ``.name``. ``str()`` of a
  proto-plus ``IntEnum`` is its number (``"2"``) on Python 3.11 and later, so a substring test
  over it never saw ``MATCH_FOUND`` and allowed everything. ``MATCH_FOUND`` blocks, and so does
  an absent or empty sanitization result (proto-plus hands back an empty message, whose state is
  ``FILTER_MATCH_STATE_UNSPECIFIED``): a screen that did not say "no match" has not said
  "allowed";
- ``invocation_result`` is set independently of the match state. ``PARTIAL`` (some filters were
  skipped or failed) and ``FAILURE`` (all of them were) arrive WITH ``NO_MATCH_FOUND``, because
  a skipped filter reports ``EXECUTION_SKIPPED`` and no match. A filter skips when the text
  exceeds its token limit, when the language is unsupported (multi-language detection is off
  wherever ``var.model_armor_full_capabilities`` is false), or when a detector errors. "No
  match" from a screen that did not run is not a clean pass, so anything short of ``SUCCESS``
  blocks, and padding a prompt past the prompt-injection filter's limit gets it refused rather
  than through unscreened;
- an API error, including the deadline, propagates to the domain, which audits the refusal and
  fails the request.

The ``google.cloud.modelarmor_v1`` import is lazy so the ``local``/``onprem`` profiles import
this module with no GCP SDK installed (the portability proof, P-02). The SDK is declared in the
``[gcp]`` extra and pinned in ``requirements-gcp.lock``, so the runtime image carries it and
``lint-gcp`` type-checks this module against it.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.kernel import Direction, GuardrailCategory, GuardrailFinding, GuardrailVerdict

#: The one filter state that allows. Compared against the enum member's NAME, never str().
_NO_MATCH = "NO_MATCH_FOUND"
_MATCH = "MATCH_FOUND"
#: The one invocation result that allows: every configured filter ran. Also compared by NAME.
_ALL_FILTERS_RAN = "SUCCESS"


class ModelArmorGuardrailAdapter:
    """Screen prompts/responses through a regional Model Armor template."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._armor = settings.model_armor
        #: Injected only by tests, which drive the real request and response types through a
        #: recording client; every binding constructs it lazily from the regional host.
        self._client: Any | None = client

    def _template(self) -> str:
        return (
            f"projects/{self._settings.project_id}/locations/{self._settings.region}"
            f"/templates/{self._armor.template_id}"
        )

    def _get_client(self) -> Any:
        if self._client is None:  # pragma: no cover - constructing it resolves live credentials
            from google.api_core.client_options import ClientOptions
            from google.cloud import modelarmor_v1

            self._client = modelarmor_v1.ModelArmorClient(
                client_options=ClientOptions(api_endpoint=self._armor.host),
            )
        return self._client

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen inbound prompt or outbound response text. Raises if Model Armor cannot answer."""
        from google.cloud import modelarmor_v1  # lazy

        client = self._get_client()
        template = self._template()
        timeout = self._armor.timeout_seconds
        response: (
            modelarmor_v1.SanitizeUserPromptResponse | modelarmor_v1.SanitizeModelResponseResponse
        )
        if direction is Direction.INPUT:
            response = client.sanitize_user_prompt(
                request=modelarmor_v1.SanitizeUserPromptRequest(
                    name=template,
                    user_prompt_data=modelarmor_v1.DataItem(text=text),
                ),
                timeout=timeout,
            )
        else:
            response = client.sanitize_model_response(
                request=modelarmor_v1.SanitizeModelResponseRequest(
                    name=template,
                    model_response_data=modelarmor_v1.DataItem(text=text),
                ),
                timeout=timeout,
            )
        return self._map_result(response, direction, text)

    @staticmethod
    def _map_result(response: Any, direction: Direction, original: str) -> GuardrailVerdict:
        """Map a sanitize response to a verdict: allowed ONLY on a complete, clean screen.

        Complete means ``invocation_result`` is ``SUCCESS``; clean means ``filter_match_state``
        is ``NO_MATCH_FOUND``. Model Armor reports a decision, not a rewrite, for these filters,
        so an allowed verdict carries the screened text unchanged.
        """
        result = getattr(response, "sanitization_result", None)
        name = getattr(getattr(result, "filter_match_state", None), "name", None)
        invocation = getattr(getattr(result, "invocation_result", None), "name", None)
        if name == _NO_MATCH and invocation == _ALL_FILTERS_RAN:
            return GuardrailVerdict(
                allowed=True, direction=direction, sanitized_text=original, reason="ok"
            )
        if name == _MATCH:
            # A match is a match however many filters ran: the block needs no complete screen.
            reason = "blocked by Model Armor"
            detail = "Model Armor filter match"
        elif name == _NO_MATCH:
            reason = "blocked: Model Armor returned no complete filter decision"
            detail = f"invocation_result={invocation or 'absent'}: not every filter ran"
        else:
            reason = "blocked: Model Armor returned no filter decision"
            detail = f"filter_match_state={name or 'absent'}"
        finding = GuardrailFinding(
            category=GuardrailCategory.OTHER, confidence="high", detail=detail
        )
        return GuardrailVerdict(
            allowed=False,
            direction=direction,
            findings=(finding,),
            sanitized_text=None,
            reason=reason,
        )
