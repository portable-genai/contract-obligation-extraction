"""Remove the ``ui/`` micro-frontend and everything that watches it, in one consistent step.

A repo with no user-facing surface should not carry a UI, and deleting the directory by hand is
not enough: the npm dependabot ecosystem would keep pointing at a directory that no longer
exists (dependabot errors on that), and a CI job would keep running with nothing to gate.
``tests/unit/test_ui_surface.py`` therefore checks the three in BOTH directions and fails the
offline gate until they agree, so this script exists to make agreeing cheap.

    make drop-ui

It is idempotent: running it in a repo that already has no UI reports what was already gone and
changes nothing. It does NOT delete the ``ui-*`` targets from the ``Makefile``, on purpose: they
are harmless with no ``ui/`` present, and leaving them makes re-adding a UI a copy rather than an
archaeology exercise.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The dependabot entry to remove, matched by its ``directory:`` line so a reformatted file or a
#: changed schedule still matches. A brittle full-text match would silently no-op.
_NPM_DIRECTORY = "directory: /ui"


def _strip_npm_ecosystem(text: str) -> str:
    """Drop the npm update block (and the comment paragraph above it) from dependabot.yml."""
    lines = text.splitlines()
    keep: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("- package-ecosystem: npm"):
            # Walk back over the comment paragraph that introduces this block.
            while keep and (keep[-1].strip().startswith("#") or not keep[-1].strip()):
                keep.pop()
            index += 1
            # Then forward to the next top-level list item, or the end of the file.
            while index < len(lines) and not lines[index].strip().startswith("- package-ecosystem"):
                index += 1
            keep.append("")
            continue
        keep.append(line)
        index += 1
    return "\n".join(keep).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove ui/ and everything that watches it.")
    parser.add_argument("--dry-run", action="store_true", help="report what would change only")
    args = parser.parse_args(argv)

    changes: list[str] = []
    unchanged: list[str] = []

    ui = REPO_ROOT / "ui"
    if ui.exists():
        changes.append("removed ui/")
        if not args.dry_run:
            shutil.rmtree(ui)
    else:
        unchanged.append("ui/ was already absent")

    workflow = REPO_ROOT / ".github" / "workflows" / "ui-gate.yaml"
    if workflow.exists():
        changes.append("removed .github/workflows/ui-gate.yaml")
        if not args.dry_run:
            workflow.unlink()
    else:
        unchanged.append("the ui-gate workflow was already absent")

    dependabot = REPO_ROOT / ".github" / "dependabot.yml"
    text = dependabot.read_text(encoding="utf-8")
    if _NPM_DIRECTORY in text:
        stripped = _strip_npm_ecosystem(text)
        if _NPM_DIRECTORY in stripped:
            print("could not remove the npm ecosystem cleanly; edit .github/dependabot.yml")
            return 1
        changes.append("removed the npm ecosystem from .github/dependabot.yml")
        if not args.dry_run:
            dependabot.write_text(stripped, encoding="utf-8")
    else:
        unchanged.append("dependabot already had no npm ecosystem")

    for line in changes:
        print(("would have " if args.dry_run else "") + line)
    for line in unchanged:
        print(line)
    if changes and not args.dry_run:
        print("")
        print("The ui-* Makefile targets were left in place, so re-adding a UI stays a copy.")
        print("Run `make gate` and review the diff before committing.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
