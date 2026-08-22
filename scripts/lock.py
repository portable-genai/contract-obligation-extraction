#!/usr/bin/env python3
"""Compile both lockfiles and put the header back, because `uv pip compile` overwrites it.

`uv pip compile` REPLACES the output file. It emits its own two-line provenance comment and
nothing else, so every time the documented `make lock` command ran, the header block below was
destroyed: the explanation of why the commons are pinned by COMMIT rather than by tag, and the
`tag = commit` map that `tests/unit/test_repo_artifacts.py` checks the pins against.

That is not hypothetical. One catalog repo has been carrying exactly this damage, with a red gate,
since somebody ran the command and committed the result. Nothing warned them: `uv` succeeded, the
file looked plausible, and the only symptom was two failing tests in a suite nobody re-read.

So the fix is not "remember to restore the header". A convention that depends on remembering has
already failed once here. `make lock` runs this script instead, the header is re-applied from the
map this file computes, and the companion test fails the build if a lockfile ever appears without
it. Run it after any dependency change and commit both files.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

#: Commons packages pinned by git reference. The KNOWN order keeps existing headers stable; any
#: other git-pinned package is appended, because a repo may pin a commons this list has never
#: heard of (one pins `speech-lexicon-kit`) and a fixed allowlist would silently omit it from the
#: map, which is exactly the incompleteness the pin test then fails on.
_KNOWN_ORDER = ("hex-service-kit", "agent-eval-kit", "review-kit", "pii-kit")


def _commons_order(names: set[str]) -> list[str]:
    known = [n for n in _KNOWN_ORDER if n in names]
    return known + sorted(names - set(known))


#: (extra, output file) for each lockfile the repo ships.
_TARGETS = (("dev", "requirements-dev.lock"), ("gcp", "requirements-gcp.lock"))

#: `name[extras] @ git+URL@vTAG`, the shape every commons dependency is declared in.
_GIT_PIN = r"([a-z0-9-]+)(?:\[[^\]]*\])?\s*@\s*git\+\S+?@(v[0-9][^\s\"']*)"

_HEADER = """\
# Compiled dependency lock. DO NOT hand-edit: run `make lock` and commit the result.
#
#   uv pip compile pyproject.toml --extra {extra} --universal -o {output}
#
# --universal resolves across every interpreter in the CI matrix, so ONE lockfile installs on
# all of them. Everything is pinned to an exact version, and the catalog commons are pinned to a
# 40-character COMMIT SHA rather than to the tag `pyproject.toml` names.
#
# A tag is a movable pointer. A lockfile that pins a tag installs whatever that tag points at on
# the day pip runs, so a re-pushed tag changes what ships with NO diff in this file and no way to
# notice: it breaks the reproducible-install claim (practices check D1) exactly where the claim is
# supposed to be strongest. A commit cannot move.
#
# Dereference a tag with `git rev-list -n 1 <tag>`, NOT `git rev-parse <tag>`. These are ANNOTATED
# tags, so `rev-parse` returns the tag OBJECT (a different sha that is not a commit); pinning one
# of those is a lockfile that looks pinned and does not install.
#
# tag -> commit, and `tests/unit/test_repo_artifacts.py` proves each line against the tag
# `pyproject.toml` names and against the other lockfile:
{tag_map}
"""


def _declared_tags(extra: str) -> dict[str, str]:
    """Each commons package mapped to the tag `pyproject.toml` declares for it.

    Scoped to ONE lockfile: the core dependencies plus the single extra that lockfile is
    compiled with. A commons declared only in a DIFFERENT extra is legitimately absent
    here (a repo may keep `agent-eval-kit` dev-only, because the serving core never
    imports the eval scaffold), and reading every extra at once made that absence look
    like an incomplete header map.
    """
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    requirements = list(data["project"].get("dependencies", []))
    requirements.extend(data["project"].get("optional-dependencies", {}).get(extra, []))
    tags: dict[str, str] = {}
    for requirement in requirements:
        match = re.match(_GIT_PIN, requirement)
        if match:
            tags.setdefault(match.group(1), match.group(2))
    return tags


def _locked_commits(text: str) -> dict[str, str]:
    """Each commons package mapped to the 40-character commit the lockfile body pins."""
    return dict(re.findall(r"^([a-z0-9-]+) @ git\+\S+?@([0-9a-f]{40})", text, re.M))


def _header_for(extra: str, output: str, tags: dict[str, str], commits: dict[str, str]) -> str:
    both = set(tags) & set(commits)
    width = max((len(name) for name in both), default=0)
    lines = [
        f"#   {name.ljust(width)}  {tags[name]} = {commits[name]}" for name in _commons_order(both)
    ]
    return _HEADER.format(extra=extra, output=output, tag_map="\n".join(lines))


def _restore(path: Path, previous: str | None) -> None:
    """Put the file back as it was, because `uv` has already replaced it by this point.

    Every abort below happens AFTER the compile, so without this the script would leave a
    headerless lockfile behind: precisely the damage it exists to prevent, and worse than
    doing nothing because the run also reported failure and looked handled.
    """
    if previous is not None:
        path.write_text(previous, encoding="utf-8")


def main() -> int:
    for extra, output in _TARGETS:
        tags = _declared_tags(extra)
        path = _REPO_ROOT / output
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        command = [
            "uv",
            "pip",
            "compile",
            "pyproject.toml",
            "--extra",
            extra,
            "--universal",
            "-o",
            output,
        ]
        result = subprocess.run(command, cwd=_REPO_ROOT, check=False)
        if result.returncode != 0:
            _restore(path, previous)
            return result.returncode

        raw = path.read_text(encoding="utf-8")
        commits = _locked_commits(raw)
        missing = sorted(set(tags) - set(commits))
        if missing:
            _restore(path, previous)
            print(
                f"{output}: {', '.join(missing)} declared in pyproject.toml but not pinned by "
                "commit in the compiled output; the header map would be incomplete.",
                file=sys.stderr,
            )
            return 1

        # Drop uv's own provenance comment, then re-apply the real header.
        body = "\n".join(line for line in raw.splitlines() if not line.startswith("#")).lstrip("\n")
        path.write_text(_header_for(extra, output, tags, commits) + body + "\n", encoding="utf-8")
        print(f"{output}: compiled, header restored ({len(commits)} commons pinned by commit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
