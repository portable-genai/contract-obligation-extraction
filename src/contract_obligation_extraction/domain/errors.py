"""Domain exceptions for Contract Obligation Extraction.

Pure-Python exception hierarchy raised by the domain services. The domain layer never imports a
cloud SDK or a web framework; these errors let callers (the API, the CLI, the agent tool) react
to domain-level failures without coupling to any vendor SDK error type.
"""

from __future__ import annotations


class TriageError(Exception):
    """Base class for all domain-level errors this service raises."""


class GuardrailBlockedError(TriageError):
    """Raised when the guardrail blocks a triage input or the narrated output (rule R1).

    A blocked call must never yield a partial or substitute result: the domain service raises
    this rather than returning a triage built on unsafe text, and the caller audits the attempt
    as ``Decision.BLOCKED`` before the raise reaches it.
    """
