"""GuardrailPort: the boundary that screens a generation call in both directions (rule R1).

Rule R1 is the reason this port exists: a service that binds ``agent-guardrail-gateway`` as a
mandatory dependency must screen every inbound prompt BEFORE it reaches a model or the domain's
own narration, and every outbound answer AFTER it is produced and BEFORE it is audited or
returned. ``domain/triage_service.py`` calls :meth:`GuardrailPort.screen` around its narration
step in exactly that shape, and ``domain/narration.py`` calls it around the real generation call
this vertical makes (the register summary, ``adapters/gcp/generation.py``), so both the
scaffolded triage path and the vertical's own model call are screened in both directions.

The domain stays pure. This port names the screen; the adapters (not this module) depend on the
managed guardrail service (Model Armor) or a local heuristic stand-in.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.kernel import Direction, GuardrailVerdict


@runtime_checkable
class GuardrailPort(Protocol):
    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        """Screen inbound prompt or outbound response text; may sanitise it.

        Never raises on a policy match: a block is reported as ``GuardrailVerdict(allowed=False,
        ...)`` so the caller can audit the attempt before deciding how to fail. An allowed verdict
        carries ``sanitized_text``, the text the caller uses from then on EXACTLY as given (the
        input unchanged when nothing was redacted, possibly empty when everything was); the
        caller never falls back to the unscreened original.

        Raising is reserved for the adapter being unable to decide at all: its backend errored
        or timed out, no template is configured, or the on-prem placeholder is bound. The domain
        treats every such raise as a refusal (fail closed), audits it, and lets it propagate.
        """
        ...
