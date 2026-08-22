"""Shared, obviously fictional test data.

Fixtures are DATA, not behaviour: no test helper that makes an assertion lives here, so a
fixture module can be read as "what a case looks like" without reading a test.
"""

from __future__ import annotations

from . import sample_cases

__all__ = ["sample_cases"]
