"""GenerationPort: the LLM boundary, kept strictly to narration.

The determinism rule of this catalog is that consequential math and verdicts are pure code and
the model only narrates. This port is where the model lives, so its contract is deliberately
narrow: it turns a request (a system instruction, a prompt, the engine facts and the expected
response keys) into raw text, and nothing more. The domain owns the numbers; the narration
service validates the model's text against a schema and discards it on failure, so a model that
invents a figure changes nothing a caller relies on.

The domain stays pure: this is a Protocol. The adapters (not this module) reach a real model
under the managed profile, answer deterministically offline, and fail fast on-premises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """One narration request. ``facts`` are the engine-owned key/value pairs the note may cite.

    ``facts`` is not decoration: it is the authoritative set of figures the narration service
    grounds the model's output against. A number in the model's note that is not derivable from
    these facts is treated as a hallucination and the note is discarded.
    """

    system: str
    prompt: str
    facts: tuple[tuple[str, str], ...] = ()
    response_keys: tuple[str, ...] = ("note",)
    max_output_tokens: int = 512
    #: Sampling temperature, or ``None`` to leave it to the model. Narration is left free; pin
    #: ``0.0`` only where the output is extracted, classified, scored or compared against a
    #: deterministic check. ``None`` means the parameter is OMITTED, never sent as ``1.0``:
    #: some models (Opus 5, Fable 5) reject it outright.
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    """The raw model output. ``text`` is expected to be the structured JSON the prompt asked for."""

    text: str
    model: str = ""
    usage: tuple[tuple[str, int], ...] = field(default_factory=tuple)


@runtime_checkable
class GenerationPort(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Return the model's raw text for ``request`` (expected to be structured JSON).

        Implementations never decide anything: they narrate. A failure to reach the model is a
        raised error (the managed family) or a raised ``NotImplementedError`` (the on-premises
        placeholder), never a silent empty success that a caller could mistake for a narration.
        """
        ...
