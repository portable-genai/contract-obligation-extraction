"""The supply-chain and required-artifact posture, asserted from inside the repo.

A rendered repo is the start of 31 others, so the properties below cannot be left to a reviewer
noticing they are missing. Each assertion here corresponds to a practices check that a previous
audit found absent on day one: a claimed licence with no LICENSE file, a Dockerfile pinned to a
mutable tag and running as root, lockfiles that exist but are not what CI installs.

These are cheap file assertions, deliberately: they run in the offline gate, need no network, and
fail the build the moment one of the artifacts is deleted or quietly downgraded.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

from tests import REPO_ROOT

#: Every file the conventions list requires a repo to ship, with why it is not optional.
REQUIRED_ARTIFACTS: dict[str, str] = {
    "LICENSE": "README claims Apache-2.0; a claimed licence with no text is not a licence",
    "AGENTS.md": "the agent guidance the repo is worked on with",
    "README.md": "the front door",
    "SPEC.md": "the top of the documentation authority order",
    "ARCHITECTURE.md": "the hexagon, written down",
    "COMPLIANCE.md": "the principle and rule mapping",
    "CONTRIBUTING.md": "the extension touch list",
    "DEMO.md": "the presenter walkthrough",
    "Dockerfile": "the serving image",
    ".dockerignore": "keeps tests, docs and env files out of the image",
    "Makefile": "the gate as a target",
    "config/settings.yaml": "the adapter binding map and non-secret defaults",
    ".env.example": "the non-secret environment, reviewable and diffable",
    ".env.secrets.example": "secret NAMES with placeholder values, never real ones",
    ".github/dependabot.yml": "an ecosystem nobody watches is an unpinned dependency",
    ".github/workflows/ci.yaml": "the gate has to run somewhere",
    ".github/workflows/eval-gate.yaml": "an eval regression must block a merge on its own name",
    ".github/workflows/demo-gate.yaml": "a demo nobody runs unattended is a demo that has rotted",
    "scripts/README.md": "the demo surface needs an index, or nobody finds the entry point",
    "scripts/demo.py": "the demo is code, not a deck",
    "scripts/demo_server.py": "the live, click-through demo",
    "scripts/render_ui.py": "the static audit-first output view, for screenshots",
    "scripts/walkthrough.py": "the presenter walkthrough, which is also the demo self-test",
    "scripts/portability_demo.py": "the portability claim, executable",
    "scripts/check_docs_links.py": "documentation integrity, checked rather than reviewed",
    "requirements-dev.lock": "reproducible dev/CI installs",
    "requirements-gcp.lock": "reproducible runtime/image installs",
    "docs/runbook.md": "operating the service",
    "docs/onprem-migration.md": "the portability path",
    "docs/practices-audit.md": "the per-check verdict, so the repo never owes an unwritten audit",
}


@pytest.mark.parametrize("relative", sorted(REQUIRED_ARTIFACTS))
def test_required_artifact_is_present(relative: str) -> None:
    path = REPO_ROOT / relative
    assert path.exists(), f"missing {relative}: {REQUIRED_ARTIFACTS[relative]}"
    assert path.read_text(encoding="utf-8").strip(), f"{relative} is empty"


def test_the_licence_text_matches_the_licence_the_metadata_claims() -> None:
    licence = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in licence
    assert "Version 2.0" in licence
    assert 'license = { text = "Apache-2.0" }' in (REPO_ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_the_base_image_is_digest_pinned_not_tag_pinned() -> None:
    """A re-pushed tag can change what ships; a digest cannot."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert from_lines, "no FROM line"
    for line in from_lines:
        assert "@sha256:" in line, f"base image is not digest-pinned: {line}"


def test_the_runtime_stage_drops_root_and_declares_a_healthcheck() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER appuser" in dockerfile, "the serving process must not run as root"
    assert "HEALTHCHECK" in dockerfile, "a process that exists is not a process that serves"


def test_the_image_installs_from_the_lockfile_not_a_fresh_resolve() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install -r requirements-gcp.lock" in dockerfile
    assert "pip install --no-deps ." in dockerfile, "--no-deps keeps the lock authoritative"


def test_ci_installs_from_the_lockfiles_and_pins_the_shared_workflow() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yaml").read_text(encoding="utf-8")
    assert 'dev-lockfile: "requirements-dev.lock"' in ci
    assert 'runtime-lockfile: "requirements-gcp.lock"' in ci
    # A branch ref would silently change what this repo's gate means between two runs.
    assert "hard-gate.yaml@v" in ci, "the shared workflow must be pinned to a TAG"


def test_ci_names_an_iap_negative_matrix_that_actually_exists() -> None:
    """The one adapter whose declaration stands the exposure guard down must have a job.

    That adapter needs google-auth, which is deliberately absent from the dev lockfile, so its
    negative matrix cannot run in the offline gate and would SKIP there. `iap-matrix-path` in
    `ci.yaml` is what gives it a job with the runtime lockfile installed and the require-flag on.
    Two ways that decays silently: the input is dropped, or it names a module that was renamed or
    deleted, in which case the job runs `pytest` on nothing and reports green. Both fail here.
    """
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yaml").read_text(encoding="utf-8")
    named = [
        line.split(":", 1)[1].strip().strip('"')
        for line in ci.splitlines()
        if line.strip().startswith("iap-matrix-path:")
    ]
    assert named, (
        "ci.yaml passes no iap-matrix-path, so the IAP verifier's negative matrix has no job "
        "that installs google-auth and it skips everywhere"
    )
    for path in named:
        assert (REPO_ROOT / path).is_file(), (
            f"ci.yaml names {path}, which does not exist; the job would pass over nothing"
        )


def test_dependabot_covers_every_ecosystem_the_repo_actually_has() -> None:
    config = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    for ecosystem in ("pip", "docker", "github-actions"):
        assert f"package-ecosystem: {ecosystem}" in config, f"{ecosystem} is unwatched"
    if (REPO_ROOT / "ui" / "package.json").exists():
        assert "package-ecosystem: npm" in config, "ui/ exists, so npm must be watched"


def test_the_lockfiles_pin_every_dependency_exactly() -> None:
    """A lockfile with a range in it is not a lock."""
    for name in _discovered_lockfiles():
        for raw in (REPO_ROOT / name).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            requirement = line.split(";")[0].strip()
            assert "==" in requirement or "@ git+" in requirement, (
                f"{name}: {line!r} is not an exact pin"
            )


def _commons_refs(text: str) -> dict[str, str]:
    """Map commons package name -> the git ref it is pinned at, from a lock or pyproject."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().strip('",')
        if line.startswith("#") or "git+https://github.com/portable-genai/" not in line:
            continue
        name = line.split("@ git+", 1)[0].strip().split("[", 1)[0].strip()
        found[name] = line.rsplit("@", 1)[1]
    return found


#: The ``#   <package>  v<tag> = <commit>`` map a lockfile header carries, so the commit it pins
#: can be checked against the tag pyproject names WITHOUT a network call.
_TAG_COMMIT_LINE = re.compile(
    r"^#\s+(?P<package>[a-z0-9-]+)\s+(?P<tag>v[0-9][^\s]*)\s*=\s*(?P<commit>[0-9a-f]{40})\s*$"
)


def _discovered_lockfiles() -> tuple[str, ...]:
    """Every lockfile this repository actually carries, found by glob rather than by list.

    A hardcoded two-file list is how a blind spot gets baked into the generator. An auxiliary
    lockfile that no regeneration path and no guard enumerates sits on a superseded commons pin
    indefinitely, and that is not always cosmetic: a job that installs an auxiliary lock ON TOP
    of the dev lock pulls a kit BACKWARDS on every run, so browser evidence is gathered against
    the very fail-open a newer release closed.

    A render ships two lockfiles, which is the only reason a two-name list would not break
    anything here. A repository that grows a third would silently stop being checked, and
    "silently stop being checked" is indistinguishable from "checked and fine" in a gate summary.
    """
    return tuple(sorted(path.name for path in REPO_ROOT.glob("requirements-*.lock")))


_LOCKFILES = _discovered_lockfiles()


def test_the_lockfile_discovery_actually_finds_the_lockfiles() -> None:
    """A glob that matches nothing turns every test parametrized on it into a silent pass.

    This is the failure mode the glob was introduced to avoid, reappearing one level up: an
    empty `_LOCKFILES` makes `pytest.mark.parametrize` generate zero cases, and zero cases is
    reported as success. The dev lock is the one every repository has.
    """
    assert _LOCKFILES, "no requirements-*.lock found; the lockfile guards would assert nothing"
    assert "requirements-dev.lock" in _LOCKFILES, (
        f"discovered {_LOCKFILES}, which does not include the dev lock every repository carries"
    )


def _tag_commit_map(text: str) -> dict[str, tuple[str, str]]:
    """Map package -> (tag, commit) from a lockfile header."""
    found: dict[str, tuple[str, str]] = {}
    for raw in text.splitlines():
        match = _TAG_COMMIT_LINE.match(raw)
        if match:
            found[match["package"]] = (match["tag"], match["commit"])
    return found


@pytest.mark.parametrize("name", _LOCKFILES)
def test_the_lockfiles_pin_the_commons_to_a_commit_not_a_movable_tag(name: str) -> None:
    """A tag is a pointer somebody can move; a lockfile that pins one is not a lock.

    A re-pushed tag changes what installs with NO diff in the lockfile and nothing in the repo
    to notice it, which is the reproducible-install claim failing exactly where it is supposed
    to be strongest. Every one of the 22 built repos pins the 40-character commit; a repo
    rendered from this template must be born pinning it too, not receive it in a later sweep.

    SHAPE ONLY, and that is not enough on its own: an ANNOTATED TAG OBJECT's sha is also 40 hex
    characters, so this passes a lockfile pinned at ``git rev-parse <tag>`` output, which is the
    exact mistake that was swept out of five repos. The check that can tell them apart is
    ``test_each_locked_sha_is_a_commit_object_and_not_a_tag_object`` below, which asks git.
    """
    locked = _commons_refs((REPO_ROOT / name).read_text(encoding="utf-8"))
    assert locked, f"{name} pins no commons at all"
    for package, ref in sorted(locked.items()):
        assert re.fullmatch(r"[0-9a-f]{40}", ref), (
            f"{name} pins {package} at {ref!r}, which is not a 40-character commit sha. "
            "Dereference the tag with `git rev-list -n 1 <tag>` (NOT `git rev-parse <tag>`, "
            "which returns the annotated tag object) and pin the commit."
        )


# --------------------------------------------------------------------------------------- #
# The pinned sha is a COMMIT object, asked of git rather than of a regular expression.
#
# The defect this exists for: an adversarial verifier replaced review-kit's commit with the
# sha of its ANNOTATED TAG OBJECT in both lockfiles AND in the header tag map, and the whole gate
# stayed green. Every structural check above still passed, because both shas are 40 hex
# characters and the three artifacts agreed with each other. Nothing about a sha says what kind
# of object it names; only an object store can answer that, so this asks one.
#
# Offline: a LOCAL object store, never the network. `git ls-remote` would answer beautifully and
# would put the gate on the internet, which it must never be.
# --------------------------------------------------------------------------------------- #
#: A directory holding clones of the commons repos, one per package name. Set it when the
#: checkouts are not siblings of this repo. Read two-state deliberately: it names a search path
#: and grants nothing, and an emptied value simply finds no store, which is the same as unset.
_CHECKOUT_ROOT_ENV = "COMMONS_GIT_CHECKOUT_ROOT"


def _git(store: Path, *args: str) -> str | None:
    """Run git in ``store``; ``None`` when git is absent or the command failed."""
    if shutil.which("git") is None:  # pragma: no cover - git is present in the gate
        return None
    completed = subprocess.run(
        ["git", "-C", str(store), *args], capture_output=True, text=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _installed_source_dir(package: str) -> Path | None:
    """The local directory a package was installed FROM, when it was installed from one.

    PEP 610 records the install's provenance in ``direct_url.json``. An editable install (what
    the template's own render harness does) and a ``git+file://`` install both record a
    ``file://`` URL, and in this workspace that directory is the commons repo's git work tree.
    A ``git+https://`` install records the remote URL and no local path, so this returns None
    and the search falls through.
    """
    try:
        raw = metadata.distribution(package).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    url = str(json.loads(raw).get("url", ""))
    if not url.startswith("file://"):
        return None
    return Path(unquote(urlparse(url).path))


def object_stores(package: str) -> list[Path]:
    """Every local git work tree that might hold ``package``'s objects, best guess first."""
    candidates: list[Path | None] = []
    root = os.environ.get(_CHECKOUT_ROOT_ENV, "").strip()
    if root:
        candidates.append(Path(root) / package)
    # The polyrepo workspace: every catalog repo sits next to the commons it pins.
    candidates.append(REPO_ROOT.parent / package)
    candidates.append(_installed_source_dir(package))
    return [
        path
        for path in candidates
        if path is not None and path.is_dir() and _git(path, "rev-parse", "--git-dir") is not None
    ]


def git_object_type(store: Path, sha: str) -> str | None:
    """``commit`` / ``tag`` / ..., or ``None`` when this store does not have the object.

    A store that has never fetched the object is NO evidence, in either direction, so it is
    reported as absent and the caller keeps looking. Only a positive answer decides anything.
    """
    return _git(store, "cat-file", "-t", sha)


def pin_verdict(package: str, sha: str, tag: str) -> tuple[str, str] | None:
    """``(verdict, detail)`` from the first store that knows ``sha``, or None if none does."""
    for store in object_stores(package):
        kind = git_object_type(store, sha)
        if kind is None:
            continue
        if kind != "commit":
            return "not-a-commit", f"{store} says {sha} is a {kind} object, not a commit"
        # The store knows the object AND may know the tag; when it does, tie the two together.
        # `rev-list -n 1` dereferences an annotated tag to its commit, which `rev-parse` does
        # not, and that difference is the whole defect.
        dereferenced = _git(store, "rev-list", "-n", "1", tag)
        if dereferenced is not None and dereferenced != sha:
            return "wrong-commit", f"{store} says {tag} is {dereferenced}, not {sha}"
        return "commit", str(store)
    return None


@pytest.mark.parametrize("name", _LOCKFILES)
def test_each_locked_sha_is_a_commit_object_and_not_a_tag_object(name: str) -> None:
    """Ask git what the pinned object IS. A regular expression cannot, and never could.

    Skips only when no local object store can answer for any package at all: a check with no
    evidence has proved nothing and must say so rather than pass. `scripts/verify-render.sh`
    asserts that this does NOT skip there, because the render harness installs the commons from
    their sibling checkouts and therefore always has evidence.
    """
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    locked = _commons_refs(text)
    recorded = _tag_commit_map(text)
    checked: list[str] = []
    unknown: list[str] = []
    for package, sha in sorted(locked.items()):
        tag = recorded.get(package, ("", ""))[0]
        verdict = pin_verdict(package, sha, tag)
        if verdict is None:
            unknown.append(package)
            continue
        kind, detail = verdict
        assert kind == "commit", (
            f"{name} pins {package} at {sha}, and {detail}. An annotated tag object's sha is "
            "also 40 hex characters, so it passes every shape check while installing nothing "
            "reproducible. Dereference with `git rev-list -n 1 <tag>`, never `git rev-parse`."
        )
        checked.append(package)
    if not checked:
        pytest.skip(
            f"no local git object store holds any of {unknown}, so the pinned objects' TYPE "
            f"cannot be established offline. Clone the commons next to this repo, or set "
            f"{_CHECKOUT_ROOT_ENV} to a directory holding them."
        )


def test_the_object_type_check_can_tell_a_tag_object_from_a_commit(tmp_path: Path) -> None:
    """The positive control, on a repo built here: a green tick nobody proved is decoration.

    Builds a throwaway repository with an ANNOTATED tag, which is the only kind that produces a
    second 40-hex sha, and proves the helper distinguishes the two objects. Without this, a
    `git_object_type` that quietly returned None forever would make the test above skip its way
    to green in every environment.
    """
    if shutil.which("git") is None:  # pragma: no cover - git is present in the gate
        pytest.skip("git is not installed")
    store = tmp_path / "repo"
    store.mkdir()
    (store / "file.txt").write_text("synthetic", encoding="utf-8")
    for args in (
        ("init", "-q"),
        ("config", "user.email", "gate@example.invalid"),
        ("config", "user.name", "Gate"),
        ("add", "file.txt"),
        ("commit", "-q", "-m", "one"),
        ("tag", "-a", "v9.9.9", "-m", "annotated"),
    ):
        assert _git(store, *args) is not None, f"git {args[0]} failed building the fixture"
    commit = _git(store, "rev-list", "-n", "1", "v9.9.9")
    tag_object = _git(store, "rev-parse", "v9.9.9")
    assert commit and tag_object and commit != tag_object, (
        "the fixture did not produce an annotated tag, so it cannot prove the distinction"
    )
    assert git_object_type(store, commit) == "commit"
    assert git_object_type(store, tag_object) == "tag", (
        "`git rev-parse <annotated tag>` returns a TAG object whose sha is also 40 hex "
        "characters. That is the whole defect, and the check must be able to see it."
    )
    assert git_object_type(store, "0" * 40) is None, "an unknown object is not evidence"


def test_both_lockfiles_pin_the_commons_at_the_same_commits() -> None:
    """The dev gate and the shipped image must install the same commons, or the gate proves less."""
    dev, runtime = (
        _commons_refs((REPO_ROOT / name).read_text(encoding="utf-8")) for name in _LOCKFILES
    )
    shared = sorted(set(dev) & set(runtime))
    assert shared, "the two lockfiles have no commons in common; one of them is not being read"
    for package in shared:
        assert dev[package] == runtime[package], (
            f"{package}: dev lock pins {dev[package]}, runtime lock pins {runtime[package]}"
        )


@pytest.mark.parametrize("name", _LOCKFILES)
def test_each_locked_commit_is_recorded_against_the_tag_pyproject_names(name: str) -> None:
    """The offline proof that the pinned commit IS the pinned tag.

    ``pyproject.toml`` names a tag (a human-readable release line) and the lockfile pins the
    commit that tag pointed at. Two homes for one pin is one home too many unless they are tied
    together, so each lockfile carries a ``tag = commit`` map in its header and this asserts the
    three-way agreement: the map's commit is what the lockfile installs, and the map's tag is
    what pyproject declares.
    """
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    locked = _commons_refs(text)
    declared = _commons_refs((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    recorded = _tag_commit_map(text)
    assert declared, "pyproject pins no commons; the template is meant to pin four"
    assert set(recorded) == set(locked), (
        f"{name}: the header tag map covers {sorted(recorded)} but the file pins {sorted(locked)}"
    )
    for package, (tag, commit) in sorted(recorded.items()):
        assert package in declared, f"{name} pins {package}, which pyproject does not"
        assert commit == locked[package], (
            f"{name}: header records {package} at {commit}, the pin says {locked[package]}"
        )
        assert tag == declared[package], (
            f"{name}: header records {package} {tag}, pyproject declares {declared[package]}"
        )


def test_pyproject_names_a_tag_so_a_bump_stays_readable() -> None:
    """The tag is the reviewable half of the pin; a diff of two shas says nothing to a human."""
    declared = _commons_refs((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for package, ref in sorted(declared.items()):
        assert re.fullmatch(r"v[0-9][0-9a-zA-Z.\-+]*", ref), (
            f"pyproject pins {package} at {ref!r}; it should name the release TAG, and the "
            "lockfiles should carry the commit that tag resolves to."
        )


def test_no_secret_value_is_committed_in_the_example_env_files() -> None:
    for name in (".env.example", ".env.secrets.example"):
        for raw in (REPO_ROOT / name).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            _, _, value = line.partition("=")
            assert value.strip() in ("", "REPLACE_WITH_SECRET") or not name.endswith(
                "secrets.example"
            ), f"{name} appears to carry a real value: {line!r}"


@pytest.mark.parametrize("name", _LOCKFILES)
def test_each_lockfile_keeps_the_header_uv_would_have_destroyed(name: str) -> None:
    """`uv pip compile` REPLACES the output file, header and all.

    The test above proves the tag map is correct. This one guards the reason it can go missing in
    the first place, because that failure has already happened in this catalog: somebody ran the
    documented `make lock`, uv emitted its own two-line provenance comment in place of the whole
    header, and the repo shipped a lockfile with no map at all. Nothing warned them. uv succeeded,
    the file looked plausible, and the only symptom was two failing tests in a suite nobody
    re-read before committing.

    So `make lock` goes through `scripts/lock.py`, which re-applies the header after compiling,
    and this asserts the header actually survived rather than trusting that it will.
    """
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    assert text.startswith("# Compiled dependency lock."), (
        f"{name} has lost its header. `uv pip compile` overwrites the file, so run `make lock` "
        "(which goes through scripts/lock.py) rather than uv directly."
    )
    # The prose is the part a reader needs and a regenerator silently drops.
    assert "A commit cannot move." in text
    assert "git rev-list -n 1" in text


def test_the_lock_target_cannot_reintroduce_the_bare_uv_command() -> None:
    """The Makefile must not call `uv pip compile` directly, or the header goes again."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    lock_target = makefile.split("\nlock:", 1)[1].split("\n\n", 1)[0]
    assert "scripts/lock.py" in lock_target, "the lock target must go through scripts/lock.py"
    assert "uv pip compile" not in lock_target, (
        "calling uv directly here is what destroyed a lockfile header once already"
    )
