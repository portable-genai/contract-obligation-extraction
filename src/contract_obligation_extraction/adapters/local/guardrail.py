"""Local GuardrailPort: heuristic prompt-injection / jailbreak screening.

The ``local`` profile's stand-in for **Model Armor**: a deterministic heuristic that allows
benign text and BLOCKS on prompt-injection / jailbreak patterns (e.g. "ignore all previous
instructions", "exfiltrate", "system prompt"). Deterministic so the blocked-path tests pass by
feeding malicious vs benign text rather than by swapping in a special fake. There is no Google
emulator for Model Armor, so this path is unconditional.
"""

from __future__ import annotations

import re

from ...config import Settings
from ...domain.kernel import Direction, GuardrailCategory, GuardrailFinding, GuardrailVerdict

_INJ = GuardrailCategory.PROMPT_INJECTION
_JB = GuardrailCategory.JAILBREAK

# (pattern, category). Any match blocks the request; the checks are intentionally cheap and
# offline, never a claim to match what the managed service screens for. Each is bounded by word
# boundaries, and each is case-insensitive except where CASE is the signal: a heuristic that
# refuses a customer called Dan, or "the system prompted me to reset", blocks ordinary cases.
_INJECTION_PATTERNS: tuple[tuple[re.Pattern[str], GuardrailCategory], ...] = (
    (re.compile(r"\bignore\s+(all\s+)?(the\s+)?previous\s+instructions\b", re.I), _INJ),
    (re.compile(r"\bdisregard\s+(all\s+)?(the\s+)?(prior|previous)\s+", re.I), _INJ),
    # The NOUN phrase, not the verb: "system prompts" is a target, "system prompted" is not.
    (re.compile(r"\bsystem\s+prompts?\b", re.I), _INJ),
    (re.compile(r"\bexfiltrat", re.I), _INJ),
    (re.compile(r"\breveal\s+(your\s+)?(secret|api\s*key|credential)", re.I), _INJ),
    (re.compile(r"\bjailbreak", re.I), _JB),
    # The "DAN" persona is written in capitals; the given name Dan is not, so this one is
    # case-SENSITIVE. The persona's own expansion is matched in any case.
    (re.compile(r"\bDAN\b"), _JB),
    (re.compile(r"\bdo\s+anything\s+now\b", re.I), _JB),
    (re.compile(r"\boverride\s+(your\s+)?safety", re.I), _JB),
)


class LocalHeuristicGuardrailAdapter:
    """Heuristic guardrail: allow benign text, block known injection / jailbreak patterns."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        findings = tuple(
            GuardrailFinding(
                category=category,
                confidence="high",
                detail=f"matched {category.value} pattern",
            )
            for pattern, category in _INJECTION_PATTERNS
            if pattern.search(text or "")
        )
        if findings:
            return GuardrailVerdict(
                allowed=False,
                direction=direction,
                findings=findings,
                sanitized_text=None,
                reason="blocked by guardrail: prompt-injection / jailbreak pattern detected",
            )
        return GuardrailVerdict(
            allowed=True,
            direction=direction,
            findings=(),
            sanitized_text=text,
            reason="ok",
        )
