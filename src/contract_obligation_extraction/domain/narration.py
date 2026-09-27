"""The narration service: the model narrates the register's figures, and never produces them.

Given a :class:`~.contracts.ContractRegister` (already computed by the deterministic engine), this
asks the generation port for a short register summary, then holds that summary to three hard
rules before it is allowed out:

* **Guardrail screening, discard on block (rule R1).** The prompt is screened INPUT before the
  generation port is ever called, and the model's raw text is screened OUTPUT before it is
  parsed, and each screen's text is used from then on exactly as handed back. Either direction
  blocking, or the guardrail failing to decide at all (it raised), is treated exactly like a
  technical narration failure: the model text is never used and the deterministic fallback is,
  because this vertical's register is never partial on account of its decorative narration --
  the same "a narration failure must degrade, never crash a decision" contract this service
  already keeps for a malformed or ungrounded response. The note is flagged, and the caller
  (``flow.py``) audits the refusal as ``Decision.BLOCKED``.
* **Schema validation, discard on failure.** The model must return JSON with the requested keys.
  Malformed output, or output missing a key, is discarded, not repaired.
* **Groundedness, discard on failure.** Every integer in the summary must be one the engine
  actually produced (the request's ``facts``). A summary that invents a figure is discarded.

When a model summary is discarded, a deterministic one built purely from the engine facts is used
instead, so a surface always has a grounded sentence and never a hallucinated one. The service
reports which path produced the note (and whether the guardrail was the reason), so the eval,
the demo and the audit trail can tell them apart.

The request-building, parsing and groundedness checks are module-level pure functions rather than
private methods, so the eval can measure the RAW model output through the very same contract the
service enforces (a groundedness metric that watched only the already-filtered service output
could never go red). Pure stdlib: the model is reached only through the injected port.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from ..ports.generation import GenerationPort, GenerationRequest
from ..ports.guardrail import GuardrailPort
from .contracts import ContractRegister
from .kernel import Direction, GuardrailVerdict

__all__ = [
    "NarratedNote",
    "NarrationService",
    "build_request",
    "fallback_text",
    "grounded_integers",
    "note_is_grounded",
    "parse_note",
]

_INT = re.compile(r"-?\d+")

_SYSTEM = (
    "You are a contract-management analyst assistant. You restate the register figures you are "
    "given as a short summary for a legal-operations reviewer. You never invent a number: use "
    "only the figures in the facts block."
)


@dataclass(frozen=True, slots=True)
class NarratedNote:
    """A register summary plus how it was produced."""

    text: str
    model_authored: bool
    grounded: bool
    #: True when the guardrail (rule R1) blocked either direction of the generation call and this
    #: is why the fallback text was used, rather than a technical failure, malformed JSON or an
    #: ungrounded figure. Distinguishing the reason is what lets a caller audit the block as the
    #: security-relevant event it is, separately from an ordinary narration failure.
    guardrail_blocked: bool = False
    #: The guardrail's own reason string when :attr:`guardrail_blocked` is True, empty otherwise.
    guardrail_reason: str = ""


def grounded_integers(facts: tuple[tuple[str, str], ...]) -> set[str]:
    """Every integer token that appears in the engine-owned facts (the grounded number set)."""
    allowed: set[str] = set()
    for _key, value in facts:
        allowed.update(_INT.findall(value))
    return allowed


def note_is_grounded(text: str, facts: tuple[tuple[str, str], ...]) -> bool:
    """True when every integer in ``text`` is one the engine facts contain."""
    allowed = grounded_integers(facts)
    return all(token in allowed for token in _INT.findall(text))


def _facts(register: ContractRegister) -> tuple[tuple[str, str], ...]:
    """The engine-owned figures the summary may cite, and nothing else grounds it."""
    counts = {name: value for name, value in register.counts}
    return (
        ("obligations", str(counts.get("obligations", 0))),
        ("flagged", str(counts.get("flagged", 0))),
        ("needs_review", str(counts.get("needs_review", 0))),
        ("overdue", str(counts.get("overdue", 0))),
        ("in_notice_window", str(counts.get("in_notice_window", 0))),
        ("dropped", str(counts.get("dropped", 0))),
        ("severity", register.severity.value),
    )


def build_request(register: ContractRegister) -> GenerationRequest:
    """The exact narration request the service sends, exposed so the eval can reuse it.

    The ``facts`` block carries the engine's numbers; the prompt instructs the model to restate
    ONLY those. The same request object is scored for groundedness by the service (on the returned
    summary) and by the eval (on the raw model output), so the two can never drift.
    """
    facts = _facts(register)
    block = "\n".join(f"{key}={value}" for key, value in facts)
    prompt = (
        f"Contract: {register.subject}\n"
        f"Facts (use ONLY these numbers):\n{block}\n"
        'Return JSON of the form {"note": "<one sentence>"}.'
    )
    return GenerationRequest(system=_SYSTEM, prompt=prompt, facts=facts, response_keys=("note",))


def parse_note(text: str) -> str | None:
    """Parse the model's raw text into the ``note`` string, or ``None`` if it is not valid."""
    try:
        parsed = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    note = parsed.get("note")
    if not isinstance(note, str) or not note.strip():
        return None
    return note.strip()


def fallback_text(facts: tuple[tuple[str, str], ...]) -> str:
    """A deterministic, grounded-by-construction summary built purely from the engine facts."""
    values = dict(facts)
    return (
        f"Register carries {values.get('obligations', '0')} obligations, "
        f"{values.get('flagged', '0')} flagged and {values.get('needs_review', '0')} needing "
        f"review, with {values.get('overdue', '0')} overdue deadline(s) and "
        f"{values.get('in_notice_window', '0')} inside a notice window; "
        f"{values.get('dropped', '0')} candidate(s) were dropped as uncited."
    )


class NarrationService:
    """Draft a grounded register summary for a contract register."""

    def __init__(self, generation: GenerationPort, guardrail: GuardrailPort) -> None:
        self._generation = generation
        self._guardrail = guardrail

    def narrate(self, register: ContractRegister) -> NarratedNote:
        request = build_request(register)

        # 1) Guardrail screen (INPUT), before the prompt ever reaches the generation port
        # (rule R1). The facts are engine-derived, but the subject is the counterparty name
        # lifted from client document text, so the prompt is screened AS SENT rather than
        # assumed benign, and the model is then sent the screened text exactly as handed back.
        screened_in = self._screen(request.prompt, Direction.INPUT, request.facts)
        if isinstance(screened_in, NarratedNote):
            return screened_in
        request = replace(request, prompt=screened_in)

        try:
            response = self._generation.generate(request)
        except Exception:  # noqa: BLE001 - a narration failure must degrade, never crash a decision
            return NarratedNote(
                text=fallback_text(request.facts), model_authored=False, grounded=True
            )

        # 2) Guardrail screen (OUTPUT) on the model's raw text, before it is parsed at all
        # (rule R1). A blocked output is discarded exactly like a malformed or ungrounded one,
        # and an allowed one is parsed from the screened text, never the unscreened original.
        screened_out = self._screen(response.text, Direction.OUTPUT, request.facts)
        if isinstance(screened_out, NarratedNote):
            return screened_out

        note = parse_note(screened_out)
        if note is None or not note_is_grounded(note, request.facts):
            # Schema-invalid or ungrounded: discard the model output, never repair it.
            return NarratedNote(
                text=fallback_text(request.facts), model_authored=False, grounded=True
            )
        return NarratedNote(text=note, model_authored=True, grounded=True)

    def _screen(
        self, text: str, direction: Direction, facts: tuple[tuple[str, str], ...]
    ) -> str | NarratedNote:
        """Screen one direction: the text to use from here on, or the flagged fallback note.

        A guardrail that RAISES has not decided, so it fails closed exactly like a block: the
        model text is never used, and the caller audits the refusal from the flagged note. It is
        not re-raised, because the narration is decorative by design and the register it
        describes has already been admitted and audited; the fallback is the fixed text.
        """
        try:
            verdict: GuardrailVerdict = self._guardrail.screen(text, direction)
        except Exception as exc:  # noqa: BLE001 - fail closed onto the fixed text, audited
            return _refused_note(facts, direction, f"guardrail unavailable ({type(exc).__name__})")
        if not verdict.allowed or verdict.sanitized_text is None:
            reason = verdict.reason or f"blocked by guardrail ({direction.value})"
            return _refused_note(facts, direction, reason)
        return verdict.sanitized_text


def _refused_note(
    facts: tuple[tuple[str, str], ...], direction: Direction, reason: str
) -> NarratedNote:
    """The grounded fallback, flagged so a caller can audit the refusal (rule R1).

    Never a partial or substitute narration built on the refused text: the fallback is
    built purely from the engine's own facts, exactly as it is for any other narration
    failure, and is grounded by construction.
    """
    return NarratedNote(
        text=fallback_text(facts),
        model_authored=False,
        grounded=True,
        guardrail_blocked=True,
        guardrail_reason=f"{direction.value}: {reason}",
    )
