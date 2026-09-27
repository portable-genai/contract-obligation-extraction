"""On-prem GuardrailPort: fail-fast portability placeholder (the sovereign-exit proof, P-12).

The adapter constructs cleanly with no external dependency and structurally satisfies the same
Protocol as the managed adapter. ``screen`` deliberately raises rather than fail-opening: an
unimplemented guardrail must never silently allow traffic through, so porting on-premises MUST
provide a real screening backend before this port can bind here.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.kernel import Direction, GuardrailVerdict


class OnPremGuardrailAdapter:
    """Satisfies GuardrailPort but refuses at call time: the client wires its own screening."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        raise NotImplementedError(
            "on-prem guardrail is a portability placeholder: bind the client's own prompt / "
            "response screening backend (see docs/onprem-migration.md). Rule R1 still applies: "
            "every generation call is screened in both directions before this port may be "
            "switched off."
        )
