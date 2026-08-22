"""The test split is enforced, not merely conventional (bootstrap appendix step 3).

Three failures this catches, all of which look harmless in review:

1. an integration test that forgets its marker, so the "offline" gate quietly starts needing
   credentials or network on somebody else's machine;
2. a test dropped back into ``tests/`` root, where it belongs to no category and the split
   erodes one file at a time;
3. the ``integration`` marker disappearing from ``pyproject.toml``, which would turn
   ``-m 'not integration'`` into an error rather than a filter.
"""

from __future__ import annotations

import pytest

from tests import REPO_ROOT

_TESTS = REPO_ROOT / "tests"
_SUITES = ("unit", "contract", "integration")

#: Modules that legitimately live at ``tests/`` root: the package marker and the shared fixtures.
_ROOT_ALLOWED = {"__init__.py", "conftest.py"}


@pytest.mark.parametrize("suite", _SUITES)
def test_each_suite_is_a_package(suite: str) -> None:
    directory = _TESTS / suite
    assert directory.is_dir(), f"tests/{suite}/ is missing"
    assert (directory / "__init__.py").is_file(), f"tests/{suite}/__init__.py is missing"


def test_the_fixtures_directory_exists_and_is_a_package() -> None:
    """Shared data has one home, so two suites cannot disagree about the canonical case."""
    assert (_TESTS / "fixtures" / "__init__.py").is_file()


def test_no_test_module_sits_outside_a_suite() -> None:
    strays = sorted(path.name for path in _TESTS.glob("*.py") if path.name not in _ROOT_ALLOWED)
    assert strays == [], (
        f"{strays} sit in tests/ root. Move each into tests/unit, tests/contract or "
        "tests/integration so what it proves is visible from where it lives."
    )


def test_every_integration_module_is_marked_so_the_gate_skips_it() -> None:
    unmarked = [
        path.name
        for path in sorted((_TESTS / "integration").glob("test_*.py"))
        if "pytestmark = pytest.mark.integration" not in path.read_text(encoding="utf-8")
    ]
    assert unmarked == [], (
        f"{unmarked} are in tests/integration but carry no module-scope integration mark, so "
        "`pytest -m 'not integration'` would run them and the offline gate would need network."
    )


def test_the_integration_marker_is_registered() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "integration: tests that need live cloud services" in pyproject


def test_the_gate_deselects_integration_tests() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "pytest -m 'not integration'" in makefile
