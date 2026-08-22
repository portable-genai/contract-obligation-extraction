"""The PII pattern set this vertical redacts with, sourced from the shared `pii-kit`.

Row selection and ORDER are per-vertical (the commons deliberately does not bake them in): here
the national-ID rows run first and the universal email/phone rows last. A vertical with a
bare-digit account catch-all would order that last so it does not subsume a national id.
"""

from __future__ import annotations

from pii_kit import UNIVERSAL_PATTERNS, Pattern, national_patterns_for

# The jurisdictions this deployment serves (override per client). Obviously synthetic data only.
JURISDICTIONS: tuple[str, ...] = ("SG", "HK", "JP", "AU")

PII_PATTERNS: tuple[Pattern, ...] = (
    *national_patterns_for(JURISDICTIONS),
    *UNIVERSAL_PATTERNS,
)
