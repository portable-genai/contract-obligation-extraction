"""The test suite, split by what each test proves (bootstrap appendix step 3).

* ``unit/`` : one module or one service, driven by the real ``local`` adapters rather than
  bespoke fakes, so the offline implementation lives in exactly one place.
* ``contract/`` : the hexagon's boundary claims. Every port binds and conforms in every
  profile, the port map cannot drift, the SDK-free families construct with no cloud SDK
  importable, the on-premises family raises and the offline family answers.
* ``integration/`` : anything that needs a live cloud service or a reachable sibling. Every
  module here is marked ``integration``, so ``pytest -m 'not integration'`` (the gate) skips
  the whole directory; ``tests/unit/test_test_layout.py`` fails the build if one is not.

``REPO_ROOT`` lives here so a test that reads a repo file names the root once. A test that
recomputed it from its own depth would break silently the next time it moved directory.

This module also NAMES the offline profile for the whole session, below. The suite is a package
(this file exists), so ``tests.conftest`` and every test module import it first, which makes
this the earliest point in the run and the only one that is guaranteed to precede the import of
``api.app``.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The rendered repository root (the directory holding ``pyproject.toml``).
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Choose the offline profile DELIBERATELY for the test session.
#:
#: The seeded-persona identity adapter refuses to serve when the profile variable is absent (see
#: ``adapters/local/identity.py``): an unset profile must not silently hand out personas. The
#: gate IS an offline local run, so the harness says so explicitly here rather than relying on a
#: fallback, exactly as the Makefile and the CI workflows do. ``setdefault``, so a run that names
#: another profile on the command line still gets it.
#:
#: The tests that prove the UNSET behaviour override this deliberately, either in a subprocess
#: with a scrubbed environment or with ``monkeypatch.delenv`` plus a fresh module import.
os.environ.setdefault("CONTRACT_PROFILE", "local")

__all__ = ["REPO_ROOT"]
