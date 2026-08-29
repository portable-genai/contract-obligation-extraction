"""Managed-profile smoke: the gcp family against REAL services. Never part of the offline gate.

Marked ``integration`` at module scope, so ``pytest -m 'not integration'`` deselects the whole
file and the gate stays offline, credential-free and SDK-free. Run it deliberately
(``make test-integration``) against a project you are willing to write audit records into.

Each test skips rather than fails when its configuration is absent: an unconfigured machine has
not proved anything, and reporting that as a pass would be worse than reporting nothing.
"""

from __future__ import annotations

import os

import pytest

from contract_obligation_extraction.config import (
    Settings,
    build_container,
)

from tests.contract.canonical import CANONICAL_EVENT, CANONICAL_RESULT
from tests.fixtures import sample_cases

pytestmark = pytest.mark.integration

_PROJECT_ENV = "GOOGLE_CLOUD_PROJECT"
_CONSOLE_ENV = "HUMAN_REVIEW_URL"


def _managed(**overrides: object) -> Settings:
    return Settings(profile="gcp", tenant=sample_cases.TENANT, **overrides)  # type: ignore[arg-type]


@pytest.mark.skipif(not os.environ.get(_PROJECT_ENV), reason=f"{_PROJECT_ENV} is not set")
def test_the_managed_audit_sink_accepts_an_already_redacted_record() -> None:
    """Writes one obviously fictional record to the configured Cloud Logging WORM sink."""
    build_container(_managed()).audit.record(CANONICAL_EVENT)


@pytest.mark.skipif(not os.environ.get(_CONSOLE_ENV), reason=f"{_CONSOLE_ENV} is not set")
def test_an_escalation_reaches_the_live_hrz7_console() -> None:
    """Rule R8 end to end: the console answers with a review id, not just a 2xx."""
    container = build_container(_managed(review_url=os.environ[_CONSOLE_ENV]))
    reference = container.review_router.route(
        CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT
    )
    assert reference, "the console accepted the review but returned no id"
