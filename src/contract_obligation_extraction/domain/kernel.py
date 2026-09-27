"""Vertical-neutral domain kernel: pure-stdlib types the service reasons over.

Taxonomies are ``StrEnum``s from the commons (a member IS its wire value), citations carry
provenance, and the WORM audit record is stored already-redacted. Nothing here imports a web
framework or a cloud SDK (the commons packages it uses are themselves stdlib).

"Already redacted" is ENFORCED here rather than asked of every call site: see
:class:`AuditEvent`. The pattern selection comes from the sibling ``domain.pii``, which is the one
vertical-specific thing this module knows, because a boundary that cannot name the rows it masks
with is not a boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from hex_service_kit.enums import LenientStrEnum
from pii_kit import redact

from .pii import PII_PATTERNS


def utcnow() -> datetime:
    """Timezone-aware UTC now (the single clock the domain uses)."""
    return datetime.now(UTC)


class Severity(LenientStrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(LenientStrEnum):
    ALLOWED = "allowed"
    ESCALATED = "escalated"  # routed to a human (maker-checker, P-06)
    BLOCKED = "blocked"  # refused by the guardrail (rule R1); nothing built on the refused text


# --------------------------------------------------------------------------- #
# Safety (guardrail): the A1 Guardrail Gateway concerns, vertical-neutral (rule R1)
# --------------------------------------------------------------------------- #
class Direction(LenientStrEnum):
    """Which leg of a generation call a guardrail screen covers."""

    INPUT = "input"
    OUTPUT = "output"


class GuardrailCategory(LenientStrEnum):
    """What kind of thing a guardrail finding names. A fork adds to this; it never removes."""

    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SENSITIVE_DATA = "sensitive_data"
    MALICIOUS_URL = "malicious_url"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class GuardrailFinding:
    """One thing a guardrail screen noticed, never the whole verdict on its own."""

    category: GuardrailCategory
    confidence: str  # "low" | "medium" | "high"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    """What a guardrail screen decided about one direction of one generation call.

    ``sanitized_text`` is the text to use going forward when ``allowed`` is True: it may equal
    the input unchanged, and it may be SHORTER or EMPTY when the screen redacted it, and the
    caller uses it exactly as given, never falling back to the unscreened original. It is
    ``None`` when the call is blocked, because a blocked call has no safe text to substitute.
    Both halves are enforced at construction, so a verdict that is allowed with no text (or
    blocked with some) cannot exist for a caller to misread.
    """

    allowed: bool
    direction: Direction
    findings: tuple[GuardrailFinding, ...] = ()
    sanitized_text: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.allowed and self.sanitized_text is None:
            raise ValueError(
                "an allowed GuardrailVerdict must carry the text to use going forward "
                "(sanitized_text, the input unchanged when nothing was redacted)"
            )
        if not self.allowed and self.sanitized_text is not None:
            raise ValueError("a blocked GuardrailVerdict carries no sanitized_text")


@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to a generated claim (source + optional locator)."""

    source_id: str
    title: str
    snippet: str = ""


def redacted_citations(citations: tuple[Citation, ...]) -> tuple[Citation, ...]:
    """Mask EVERY field of every citation: the locator and the title as well as the snippet.

    A snippet is a slice of its source, a title is a clause heading lifted from the document, and
    a locator is routinely built from client text (``case:<the case subject>``), so all three are
    raw client text wearing a structural-looking name. No sink can tell an engine-built citation
    from an extractor-built one by inspection, so this masks unconditionally: redacting text that
    carries no identifier is a no-op, while deciding per caller is how one caller ends up
    forgetting.
    """
    return tuple(
        Citation(
            source_id=redact(c.source_id, PII_PATTERNS),
            title=redact(c.title, PII_PATTERNS),
            snippet=redact(c.snippet, PII_PATTERNS),
        )
        for c in citations
    )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, already-redacted record of one interaction (P-04 / rule R2).

    "Already redacted" as a convention each call site has to remember is not enough: a call site
    that masks ``redacted_summary`` and passes its citations through untouched writes the
    identifier into the WORM record anyway, one field away, into a record that is immutable and
    long-retained by design. So construction masks every CONTENT field: the summary, and each
    citation's locator, title and snippet. Redaction is idempotent, so a caller that already
    redacted loses nothing by the second pass.

    ``actor`` is NOT masked. It is the verified principal and is an address by design: it is
    attribution, not content, and masking it would erase the only column that says who acted.
    That is also why a leak scan runs over the content fields rather than over a whole row.

    ``severity`` is ``None`` only on a record for a request that was never scored: an INPUT
    blocked (or left undecided) by the guardrail before the severity was computed. Recording a
    band there would state a score nothing produced.
    """

    action: str
    actor: str
    decision: Decision
    severity: Severity | None
    redacted_summary: str
    citations: tuple[Citation, ...] = ()
    timestamp: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        object.__setattr__(self, "redacted_summary", redact(self.redacted_summary, PII_PATTERNS))
        object.__setattr__(self, "citations", redacted_citations(tuple(self.citations)))
