"""Documentation integrity, checked in the offline gate rather than by a reviewer's eyes.

A relative link that points at a file somebody renamed keeps rendering as a link and silently
404s; an unclosed code fence swallows the rest of a page; an em-dash slips into prose the house
style writes without one. All three are cheap to detect and expensive to notice by reading.

The checks themselves live in ``scripts/check_docs_links.py`` so that ``make docs-check`` and
this test run exactly the same code. Only RELATIVE targets are resolved, so the gate stays
offline: an external link checker would need the network and would fail honest builds whenever a
third-party host had a bad day.
"""

from __future__ import annotations

from pathlib import Path

import check_docs_links

from tests import REPO_ROOT


def test_every_relative_documentation_link_resolves() -> None:
    problems = check_docs_links.check_links(REPO_ROOT)
    assert not problems, "broken relative links:\n" + "\n".join(problems)


def test_every_code_fence_is_closed() -> None:
    problems = check_docs_links.check_fences(REPO_ROOT)
    assert not problems, "unclosed code fences:\n" + "\n".join(problems)


def test_the_shipped_prose_carries_no_em_dash_or_en_dash() -> None:
    problems = check_docs_links.check_dashes(REPO_ROOT)
    assert not problems, "forbidden dashes:\n" + "\n".join(problems)


def test_the_checker_can_actually_fail(tmp_path: Path) -> None:
    """The control case: a checker that cannot go red proves nothing when it is green."""
    broken = tmp_path / "broken.md"
    broken.write_text(
        "[gone](./nowhere.md)\n\n```python\nnever closed\nand a dash: \u2014\n",
        encoding="utf-8",
    )
    problems = check_docs_links.check_all(tmp_path)
    assert any("link target does not exist" in problem for problem in problems)
    assert any("unclosed code fence" in problem for problem in problems)
    assert any("em-dash" in problem for problem in problems)
