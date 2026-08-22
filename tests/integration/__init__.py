"""Integration tests: they need a live cloud service or a reachable sibling.

Every module in this package carries ``pytestmark = pytest.mark.integration``, so the offline
gate (``pytest -m 'not integration'``) deselects all of them and needs no credentials, no
network and no cloud SDK. Run them deliberately with ``make test-integration``.
"""
