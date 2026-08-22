"""Offline documentation checks: relative links resolve, dashes obey the house rule, fences close.

Three defects this catches, all of which a reader finds before a reviewer does:

1. **A relative link that points at nothing.** Docs get renamed and moved; the link that pointed
   at the old path keeps rendering as a link and silently 404s. Only relative targets are
   checked, so this needs no network and belongs in the offline gate.
2. **An em-dash or en-dash in shipped prose.** The catalog writes with a colon, a comma, or a
   rephrase. The rule is easy to hold and impossible to remember, so it is enforced here.
3. **An unclosed fenced code block.** One missing fence swallows the rest of a document in every
   renderer.

    make docs-check

The same function is called from the offline gate (``tests/unit/test_docs_links.py``), so a
broken link fails the build rather than waiting for somebody to run this by hand.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

#: Directories that hold generated or vendored files rather than authored documentation.
SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", "out", ".next", "dist", ".mypy_cache"}
)

#: Inline markdown links and images: the target is group 2. Reference-style definitions are
#: matched separately below, since a repo that grows them should not silently lose coverage.
_INLINE = re.compile(r"!?\[([^\]]*)\]\(\s*<?([^)<>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_REFERENCE = re.compile(r"^\[([^\]]+)\]:\s*<?([^\s>]+)>?", re.MULTILINE)

#: Schemes that leave this repository. They are NOT checked: a link checker that needs the
#: network cannot run in an offline gate, and a flaky external host would fail honest builds.
EXTERNAL = ("http://", "https://", "mailto:", "tel:", "ftp://", "//")

#: The two characters the house style forbids in shipped prose, written as escapes so this file
#: never contains one itself (a checker that trips its own rule is a checker nobody trusts).
FORBIDDEN_DASHES: dict[str, str] = {"\u2014": "em-dash", "\u2013": "en-dash"}


def _documents(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        found.append(path)
    return found


def check_links(root: Path) -> list[str]:
    """Every relative link target in every markdown file must exist on disk."""
    problems: list[str] = []
    for document in _documents(root, (".md",)):
        text = document.read_text(encoding="utf-8")
        targets = [match.group(2) for match in _INLINE.finditer(text)]
        targets += [match.group(2) for match in _REFERENCE.finditer(text)]
        for raw in targets:
            target = raw.strip()
            if not target or target.startswith("#") or target.startswith(EXTERNAL):
                continue
            path = unquote(target.split("#", 1)[0])
            if not path:
                continue
            resolved = (document.parent / path).resolve()
            if not resolved.exists():
                relative = document.relative_to(root)
                problems.append(str(relative) + ": link target does not exist: " + target)
    return problems


def check_dashes(root: Path) -> list[str]:
    """No em-dash or en-dash in shipped markdown or HTML (the catalog's house style)."""
    problems: list[str] = []
    for document in _documents(root, (".md", ".html")):
        relative = document.relative_to(root)
        for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), start=1):
            for dash, name in FORBIDDEN_DASHES.items():
                if dash in line:
                    problems.append(str(relative) + ":" + str(number) + ": " + name)
                    break
    return problems


def check_fences(root: Path) -> list[str]:
    """Every fenced code block is closed, so a missing fence cannot swallow a document."""
    problems: list[str] = []
    for document in _documents(root, (".md",)):
        opened = 0
        for line in document.read_text(encoding="utf-8").splitlines():
            if line.startswith("```"):
                opened += 1
        if opened % 2:
            problems.append(str(document.relative_to(root)) + ": unclosed code fence")
    return problems


def check_all(root: Path) -> list[str]:
    """Run every documentation check and return the problems, most structural first."""
    return check_links(root) + check_fences(root) + check_dashes(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check documentation links, fences and dashes.")
    parser.add_argument(
        "root",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1]),
        help="repository root to check (default: this repository)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    problems = check_all(root)
    if problems:
        for problem in problems:
            print(problem)
        print("")
        print("DOCS CHECK: FAILED (" + str(len(problems)) + " problems)")
        return 1
    print("DOCS CHECK: PASS (" + str(len(_documents(root, (".md",)))) + " markdown files)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
