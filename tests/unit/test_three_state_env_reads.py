"""Every security-relevant environment read resolves THREE states, proved by scanning the source.

The profile guard in ``test_profile_single_source.py`` watches ONE variable. That is not enough,
and this catalog has the scar to prove it: that guard was in place and green while two-state reads
of OTHER variables survived (a shipped ``frame-ancestors``, an audit path that fell back to an
in-memory log when emptied, an IAP audience that fell back to "verify no audience"). The defect
class is the READ, not the variable.

``os.environ.get(name, default)`` and ``os.getenv(name, default)`` collapse three states into two:

    unset          -> nobody expressed an intent, so a documented default may stand
    set and empty  -> an intent WAS expressed and it names nothing, so fail closed
    set with value -> use it

The middle state is the dangerous one. Folded into the first, a value an operator deliberately
emptied inherits the default, and where that default is the more permissive branch (a dev CORS
allowlist, a shipped ``frame-ancestors``, an in-memory audit log, an offline profile) emptying a
variable OPENS the service. ``hex_service_kit.netdefaults.read_env_setting`` returns an
``EnvSetting`` whose ``is_unset`` / ``is_configured_empty`` / ``has_value`` are mutually
exclusive, so the middle state has somewhere to go.

So this test fails the build on ANY two-state read in the shipped source, and the two escapes
from it are both narrow and both written down:

1. an EXACT-MATCH relaxation: the raw value compared against a literal,
   ``os.environ.get(X) == "1"``. There is no default to inherit and no truthiness to be
   surprised by, so unset, emptied and ``"0"`` alike all mean "no". This is the shape the commons
   itself uses for the insecure-demo opt-in, and it fails closed by construction;
2. a variable named in ``TWO_STATE_READS_WITH_A_REASON`` below, which carries no posture at all.
   Each entry needs a written reason, and a second test fails the build when an entry stops
   matching anything, so the exemption list cannot quietly outlive its reads.

``tests/`` is not scanned. A test harness legitimately manipulates the environment, and none of
it ships. Writes (``os.environ[X] = v``) are not reads and are not flagged; only ``Load`` context
counts, or a demo script pinning its own profile would read as a defect.

SCOPE LIMIT: this module parses Python with ``ast``, so no ``.mjs``/``.ts``/``.tsx`` file is ever
read. A repo with a browser tier needs the same rule expressed in that tier's own language (the
shape used here is ``ui/tests/three-state-env-reads.test.mjs``, run by ``npm test``); a
``env.UI_TENANT_ORIGINS || "*"`` once survived this entire gate because nothing scanned it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _repo_root() -> Path:
    """The repo root, found by walking up to the ``pyproject.toml``.

    Deriving it from a fixed ``parents[N]`` would bind this file to one tests layout, and the
    catalog has both a flat ``tests/`` and a split ``tests/unit/``. Walking up keeps the file
    byte-identical across repos, which is what makes drift between the copies visible.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("no pyproject.toml above this test: cannot locate the repo root")


REPO_ROOT = _repo_root()

#: Everything that ships or runs: the package, the demo surface and the eval gate. ``scripts/``
#: and ``eval/`` are in scope because a demo server and a promotion gate read the environment too,
#: and neither is exempt from the rule just because it is not imported by ``src/``.
SCANNED_ROOTS: tuple[str, ...] = ("src", "scripts", "eval")

#: variable name -> why a two-state read of it is not a posture decision. Adding an entry is a
#: reviewable claim, not a way past the test: if the variable can widen access, relax a check,
#: choose a weaker credential path, name a host, an origin, an audience or a profile, it does
#: not belong here and the read belongs in ``read_env_setting``.
TWO_STATE_READS_WITH_A_REASON: dict[str, str] = {
    "CONTRACT_QUALITY_URL": (
        "eval/run_eval.py --mode gate: the model-quality-gate promotion authority to ASK. Reaching "
        "a wrong or "
        "absent authority fails the gate; it cannot pass one. The mode itself already refuses "
        "to run off the managed profile."
    ),
    "DEMO_PORT": ("scripts/walkthrough.py: which loopback port the spawned demo server uses."),
    "DEMO_URL": (
        "scripts/walkthrough.py: attach to an already-running demo server instead of spawning "
        "one. Presenter ergonomics on loopback; the demo server binds 127.0.0.1 and is not "
        "configurable."
    ),
    "PORT": (
        "the TCP port uvicorn listens on. It grants nothing and relaxes nothing; an emptied "
        "value fails int() loudly at start-up rather than opening anything. WHICH INTERFACE is "
        "bound is the security decision, and that is resolve_bind_host, three-state already."
    ),
}

#: The commons helper that resolves all three states. Named here so the failure message can
#: point at it rather than describing it.
_THREE_STATE_READER = "read_env_setting"

#: A module carrying exactly the defect this file exists to catch, used to prove the scanner is
#: capable of failing. A scanner nobody proved can find anything is a green tick over an empty set.
_MUTANT = 'import os\nORIGINS = os.environ.get("SOME_CORS_ORIGINS", "http://x.example")\n'


def scanned_sources() -> list[Path]:
    """Every shipped Python file this rule applies to."""
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        files.extend((REPO_ROOT / root).rglob("*.py"))
    return sorted(files)


def _variable_name(node: ast.expr) -> str | None:
    """The literal variable name a read names, or ``None`` when it is computed at runtime."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    # A module constant such as ``_TOKEN_ENV``. Report the identifier: it is what a reader greps
    # for, and an exemption must name the VARIABLE, so a computed name is never exemptible.
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_environ_read(node: ast.AST) -> ast.expr | None:
    """The name argument of an ``os.environ.get`` / ``os.getenv`` / ``os.environ[...]`` READ.

    A subscript only counts in ``Load`` context: ``os.environ[X] = v`` is a write, and a demo
    script that pins its own profile that way is not making a two-state decision about anything.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and node.args:
            # os.environ.get(...)
            value = func.value
            if (
                func.attr == "get"
                and isinstance(value, ast.Attribute)
                and value.attr == "environ"
                and isinstance(value.value, ast.Name)
                and value.value.id == "os"
            ):
                return node.args[0]
            # os.getenv(...)
            if func.attr == "getenv" and isinstance(value, ast.Name) and value.id == "os":
                return node.args[0]
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and value.attr == "environ"
            and isinstance(value.value, ast.Name)
            and value.value.id == "os"
        ):
            return node.slice
    return None


def _exact_match_comparisons(tree: ast.AST) -> set[int]:
    """Node ids of environment reads compared directly against a literal.

    ``os.environ.get(X) == "1"`` has no default to inherit and no truthiness to be surprised
    by: unset, emptied, ``"0"`` and ``" 1 "`` all fail the comparison, so the relaxation stays
    off. The relaxation covers ONLY ``==``/``is`` against a non-empty literal, and only for a
    read carrying no default; ``!=`` and ``is not`` fail OPEN when the variable is unset or
    emptied and are never exempt. A test for absence uses ``read_env_setting(name).is_unset``.
    """
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not all(isinstance(op, ast.Eq | ast.Is) for op in node.ops):
            continue
        sides = [node.left, *node.comparators]
        for index, side in enumerate(sides):
            if _is_environ_read(side) is None:
                continue
            # The exemption is only for a raw read with NO inherited non-None default, compared
            # directly with a literal. ``get(X, "1") == "1"`` is unsafe: UNSET opts in while
            # SET-EMPTY opts out. Comparing two reads is unsafe too, because neither counterpart
            # is an independently reviewed literal.
            if isinstance(side, ast.Call):
                positional_default = side.args[1] if len(side.args) > 1 else None
                keyword_default = next(
                    (item.value for item in side.keywords if item.arg == "default"), None
                )
                for default in (positional_default, keyword_default):
                    if default is not None and not (
                        isinstance(default, ast.Constant) and default.value is None
                    ):
                        break
                else:
                    neighbours = sides[max(0, index - 1) : index] + sides[index + 1 : index + 2]
                    if any(
                        isinstance(other, ast.Constant)
                        and other.value is not None
                        and (not isinstance(other.value, str) or bool(other.value))
                        for other in neighbours
                    ):
                        exempt.add(id(side))
                continue
            neighbours = sides[max(0, index - 1) : index] + sides[index + 1 : index + 2]
            if any(
                isinstance(other, ast.Constant)
                and other.value is not None
                and (not isinstance(other.value, str) or bool(other.value))
                for other in neighbours
            ):
                exempt.add(id(side))
    return exempt


def environment_reads(path: Path) -> list[tuple[int, str, bool]]:
    """``(line, variable, is_exact_match)`` for every environment read in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    exempt = _exact_match_comparisons(tree)
    parents = {
        id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }
    out: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        name_node = _is_environ_read(node)
        if (
            name_node is None
            and isinstance(node, ast.Attribute)
            and node.attr in {"get", "getenv"}
            and (
                (
                    isinstance(node.value, ast.Attribute)
                    and node.value.attr == "environ"
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == "os"
                )
                or (isinstance(node.value, ast.Name) and node.value.id == "os")
            )
            and not (isinstance(parents.get(id(node)), ast.Call) and parents[id(node)].func is node)
        ):
            out.append((getattr(node, "lineno", 0), "<environment reader as value>", False))
            continue
        if name_node is None:
            continue
        name = _variable_name(name_node) or "<computed at runtime>"
        out.append((getattr(node, "lineno", 0), name, id(node) in exempt))
    return out


def _findings(path: Path) -> list[tuple[int, str]]:
    """``(line, variable)`` for every two-state read in ``path`` that has no written excuse."""
    return sorted(
        (line, name)
        for line, name, exact in environment_reads(path)
        if not exact and name not in TWO_STATE_READS_WITH_A_REASON
    )


@pytest.mark.parametrize("path", scanned_sources(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_module_reads_the_environment_two_state(path: Path) -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: reads {name} directly"
        for line, name in _findings(path)
    ]
    assert offenders == [], (
        "these reads collapse 'unset' and 'set to an empty value' into one state, so a variable "
        "an operator deliberately emptied inherits the default, which for a relaxation is the "
        f"permissive branch. Use hex_service_kit.netdefaults.{_THREE_STATE_READER}, compare the "
        "raw value against a literal, or add the variable to "
        "TWO_STATE_READS_WITH_A_REASON with a reason it carries no posture:\n"
        + "\n".join(offenders)
    )


def test_the_scan_actually_finds_a_two_state_read(tmp_path: Path) -> None:
    """A scanner nobody proved can find anything is a scanner that passes an empty tree."""
    mutant = tmp_path / "mutant.py"
    mutant.write_text(_MUTANT, encoding="utf-8")
    assert _findings(mutant) == [(2, "SOME_CORS_ORIGINS")]


def test_the_scan_accepts_the_three_state_reader_and_an_exact_match(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    clean.write_text(
        "import os\n"
        "from hex_service_kit.netdefaults import read_env_setting\n"
        'ORIGINS = read_env_setting("SOME_CORS_ORIGINS")\n'
        'OPTED_IN = os.environ.get("SOME_ALLOW_INSECURE_DEMO") == "1"\n'
        'os.environ["SOME_PROFILE"] = "local"\n',
        encoding="utf-8",
    )
    assert _findings(clean) == []


def test_the_scan_rejects_a_defaulted_or_read_to_read_comparison(tmp_path: Path) -> None:
    mutant = tmp_path / "comparison_mutant.py"
    mutant.write_text(
        "import os\n"
        'DEFAULTED = os.environ.get("SOME_RELOAD", "1") == "1"\n'
        'COUPLED = os.getenv("SOME_TOKEN") == os.getenv("OTHER_TOKEN")\n'
        'FAIL_OPEN = os.environ.get("SOME_ALLOW") != "0"\n'
        "READ = os.environ.get\n",
        encoding="utf-8",
    )
    assert _findings(mutant) == [
        (2, "SOME_RELOAD"),
        (3, "OTHER_TOKEN"),
        (3, "SOME_TOKEN"),
        (4, "SOME_ALLOW"),
        (5, "<environment reader as value>"),
    ]


def test_every_exemption_still_matches_a_real_read() -> None:
    """An exemption that outlives its read is a hole waiting for the next variable of that name."""
    read_names = {name for path in scanned_sources() for _, name, _ in environment_reads(path)}
    stale = sorted(set(TWO_STATE_READS_WITH_A_REASON) - read_names)
    assert stale == [], (
        f"{stale} are exempted from the three-state rule but nothing reads them any more. "
        "Delete the entries: an exemption list that outlives its reads silently pre-approves "
        "the next variable that happens to take one of those names."
    )


def test_every_exemption_carries_a_reason() -> None:
    unexplained = sorted(
        name for name, reason in TWO_STATE_READS_WITH_A_REASON.items() if len(reason.strip()) < 40
    )
    assert unexplained == [], (
        f"{unexplained} are exempted with no real reason written down. The exemption is a "
        "reviewable claim that the variable carries no posture; make the claim."
    )
