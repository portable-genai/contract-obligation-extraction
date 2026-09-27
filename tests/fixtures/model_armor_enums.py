"""Stdlib mirrors of the two ``modelarmor_v1`` enums the Model Armor verdict reads.

Each is an ``enum.IntEnum`` with the real member names and numbers. That is the property that
matters: ``str()`` of an ``IntEnum`` member is its NUMBER on Python 3.11 and later, exactly as
for the SDK's proto-plus enums, so a mapping that reverted to a ``str()`` substring test fails
against these as it would against the real ones. A plain-string stand-in would not, which is how
the original defect stayed green.

They exist so the verdict mapping is proved in the SDK-free ``make gate`` (which is what CI runs
on every rendered repo) and not only where ``google-cloud-modelarmor`` is installed.
``tests/unit/test_model_armor_mapping.py`` pins both to the real enums wherever the SDK is
importable, so they cannot drift from it unnoticed there.
"""

from __future__ import annotations

import enum


class FilterMatchState(enum.IntEnum):
    """``modelarmor_v1.FilterMatchState``."""

    FILTER_MATCH_STATE_UNSPECIFIED = 0
    NO_MATCH_FOUND = 1
    MATCH_FOUND = 2


class InvocationResult(enum.IntEnum):
    """``modelarmor_v1.InvocationResult``: did every configured filter run?"""

    INVOCATION_RESULT_UNSPECIFIED = 0
    SUCCESS = 1
    PARTIAL = 2
    FAILURE = 3
