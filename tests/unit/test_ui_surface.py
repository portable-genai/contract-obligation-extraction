"""The `ui/` micro-frontend's posture, asserted from the offline gate with no node installed.

Two jobs.

**Consistency in both directions.** A `ui/` with no npm dependabot ecosystem is an unwatched
lockfile; an npm ecosystem with no `ui/` is a dependabot error on every run; a `ui/` with no CI
job is a UI nobody builds. So all three are checked to agree, whichever way the repo went, and
`make drop-ui` exists to make agreeing a single step.

**The identity boundary, from the source.** The UI's security value is that the browser cannot
assert who it is. That claim is proved properly by `npm test`, which runs in the ui-gate
workflow; here it is held to the wall by cheap source assertions so that deleting the policy, or
quietly relaxing it to a wildcard, fails the SAME command a developer runs before committing,
without needing a JavaScript toolchain in the Python gate.

The source assertions are a backstop, not the guard. The guard for the environment reads is
`ui/tests/three-state-env-reads.test.mjs`, which scans this whole directory in bare node;
`tests/unit/test_three_state_env_reads.py` cannot, because it parses Python with `ast`. What is
asserted here is that the node-side guard EXISTS, runs in the command CI runs, and carries the
mutant that proves it can go red. A guard that can be deleted without failing anything is a
guard that will be.
"""

from __future__ import annotations

import json

import pytest

from tests import REPO_ROOT

UI = REPO_ROOT / "ui"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
UI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ui-gate.yaml"

#: True when this repo carries a UI at all. Everything below branches on it rather than skipping,
#: because "no UI" has its own required posture.
HAS_UI = (UI / "package.json").exists()

requires_ui = pytest.mark.skipif(not HAS_UI, reason="this repo has no ui/")


def _code_only(source: str) -> str:
    """`source` with whole-line `//` comments dropped.

    Deliberate: the UI policy modules QUOTE the two-state reads they replaced, to say what the
    defect was, and a guard that could not tell code from prose would forbid explaining the very
    thing it guards. Whole-line only, so a URL inside a string is never mistaken for a comment.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )


def test_the_ui_dependabot_ecosystem_matches_reality() -> None:
    config = DEPENDABOT.read_text(encoding="utf-8")
    watched = "package-ecosystem: npm" in config
    assert watched == HAS_UI, (
        "ui/ is present but npm is unwatched"
        if HAS_UI
        else "npm is watched but there is no ui/: dependabot errors on a missing directory. "
        "Run `make drop-ui` to remove both halves."
    )


def test_the_ui_ci_job_matches_reality() -> None:
    assert UI_WORKFLOW.exists() == HAS_UI, (
        "ui/ is present but no ui-gate workflow builds it"
        if HAS_UI
        else "the ui-gate workflow survived the removal of ui/. Run `make drop-ui`."
    )


@requires_ui
def test_the_ui_ships_a_lockfile_and_pins_every_version_exactly() -> None:
    """`npm ci` is only reproducible if the lock is committed and the manifest has no ranges."""
    assert (UI / "package-lock.json").exists(), "no package-lock.json: `npm ci` cannot run"
    manifest = json.loads((UI / "package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        for name, version in manifest.get(section, {}).items():
            assert version[0].isdigit(), name + " is not pinned exactly: " + version


@requires_ui
def test_the_ui_gate_installs_from_the_lock_and_fails_on_a_high_advisory() -> None:
    workflow = UI_WORKFLOW.read_text(encoding="utf-8")
    assert "npm ci" in workflow, "the UI job must install from the lockfile, not resolve afresh"
    assert "npm audit --audit-level=high" in workflow, "an npm advisory that only prints is unread"
    assert "run build" in workflow, "a UI that type-checks but does not build is not shipped"


@requires_ui
def test_the_client_cannot_assert_its_own_identity() -> None:
    policy = (UI / "lib" / "embed-policy.mjs").read_text(encoding="utf-8")
    for header in ("x-actor", "x-tenant", "x-roles", "x-acl", "authorization"):
        assert '"' + header + '"' in policy, header + " is not stripped from a forwarded request"
    route = (UI / "app" / "api" / "agent" / "[...path]" / "route.ts").read_text(encoding="utf-8")
    assert "stripClientIdentity" in route, "the proxy forwards client headers unfiltered"
    assert "resolveIdentity" in route, "the proxy does not resolve identity server-side"


@requires_ui
def test_identity_resolution_lives_in_one_server_side_module() -> None:
    identity = (UI / "lib" / "server" / "identity.ts").read_text(encoding="utf-8")
    # The exit profile must refuse rather than fall back to the seeded personas: a silent
    # fallback would turn a misconfigured deployment into an unauthenticated one.
    assert "onprem" in identity and "IdentityError" in identity
    assert "SEEDED_PERSONAS" in identity


@requires_ui
def test_the_ui_profile_is_read_in_three_states_like_the_service_it_fronts() -> None:
    """The same fail-open, in TypeScript, is still the same fail-open.

    An `activeProfile` doing `const raw = (env.UI_PROFILE ?? "").trim(); if (!raw) return
    "local";` lets an unset or blanked variable select the seeded-persona profile, and the proxy
    then forwards `X-Dev-Persona` (defaulting to `analyst`) to the API on every request. The
    behaviour is proved properly by `npm test`; this holds it to the wall from the Python gate,
    which is the command a developer actually runs before committing and which needs no node.
    """
    source = (UI / "lib" / "identity-policy.mjs").read_text(encoding="utf-8")
    assert "resolveProfile" in source, "there is no three-state resolver"
    assert "explicit" in source, "the resolver does not record whether anybody chose"
    # Comments are stripped first, deliberately: the module QUOTES the old two-state read to say
    # what it replaced, and a guard that could not tell code from prose would forbid explaining
    # the defect it guards.
    code = _code_only(source)
    # The exact shapes the defect took. `(requested ?? "").trim()` on the PERSONA hint is not one
    # of them and must stay legal: an unnamed persona under a deliberate local profile correctly
    # falls back to the first seeded one, because a profile was chosen.
    for fail_open in ('UI_PROFILE ?? ""', 'UI_PROFILE ?? "local"', 'return "local"'):
        assert fail_open not in code, "the two-state read is back: " + fail_open
    assert "explicit: false" in code, (
        "nothing in the resolver produces the unconsented state, so unset cannot be told apart "
        "from a chosen local"
    )
    assert (UI / "tests" / "identity-policy.test.mjs").exists(), (
        "the identity policy has no node test, so npm test proves nothing about it"
    )


@requires_ui
def test_framing_and_cors_are_allowlists_that_refuse_a_wildcard() -> None:
    """Both halves of the rule, asserted by what they DO rather than by a variable name.

    Asserting that the identifier ``WILDCARDS`` appears in the module is what a rename
    breaks while the behaviour is intact, and which a refusal covering only some spellings
    satisfies while the behaviour is not. Both halves are named here because each is a
    real gap: an exact-token set alone accepts ``https://*.example``, which CSP
    honours as a host-source wildcard, and a substring test alone accepts the literal ``null``,
    which a sandboxed iframe presents.

    The node suite is the real test; this is the drift guard that fails the OFFLINE Python gate
    if the rule is weakened, since the UI suite runs in a separate job.
    """
    policy = (UI / "lib" / "embed-policy.mjs").read_text(encoding="utf-8")
    assert "frame-ancestors" in policy
    assert 'entry.includes("*")' in policy, (
        "the refusal does not catch a wildcard INSIDE an origin, so https://*.example is "
        "accepted and emitted, and CSP honours it for every subdomain"
    )
    assert '"null"' in policy, (
        "the refusal does not catch the literal null, which a sandboxed iframe presents as its "
        "origin, so allowing it invites the framing this policy exists to refuse"
    )
    for forbidden in ('"Access-Control-Allow-Origin": "*"', "frame-ancestors *"):
        assert forbidden not in policy, "a wildcard is hard-coded: " + forbidden


@requires_ui
def test_the_framing_and_cors_allowlists_are_read_in_three_states() -> None:
    """An emptied allowlist must not answer exactly like an unset one.

    `frameAncestors` did `parseAllowlist(env.UI_FRAME_ANCESTORS)`, so unset, `""`, `"   "` and
    `","` all produced `frame-ancestors 'self'` plus `X-Frame-Options: SAMEORIGIN`, byte for
    byte. A deliberate lockdown was indistinguishable from a deployment that lost the variable,
    and the same read shape one line down governed the CORS allowlist. Proved properly by
    `ui/tests/embed-policy.test.mjs`; held to the wall here, from the command a developer
    actually runs before committing, which needs no JavaScript toolchain.
    """
    source = (UI / "lib" / "embed-policy.mjs").read_text(encoding="utf-8")
    code = _code_only(source)
    assert "readEnvSetting" in code, "the allowlists are not read through the three-state reader"
    assert "ConfiguredEmptyError" in code, "nothing refuses a present-but-empty allowlist"
    for fail_open in ("env.UI_FRAME_ANCESTORS", "env.UI_TENANT_ORIGINS"):
        assert fail_open not in code, "the two-state read is back: " + fail_open
    assert (UI / "lib" / "env-setting.mjs").exists(), "there is no three-state reader to call"
    # The refusal has to be a BUILD/BOOT refusal, not a surprise on some later request. Next
    # evaluates this file for both `next build` and `next start`.
    config = (UI / "next.config.mjs").read_text(encoding="utf-8")
    assert "assertEmbedPolicyConfigured" in config, (
        "next.config.mjs does not resolve the embedding policy, so a UI whose allowlist rendered "
        "empty still builds and still boots"
    )


@requires_ui
def test_a_node_side_guard_scans_the_ui_for_two_state_environment_reads() -> None:
    """The Python scanner cannot see this directory, so the UI needs its own.

    `tests/unit/test_three_state_env_reads.py` walks `src`, `scripts` and `eval` and parses with
    `ast`, so no `.mjs`, `.ts` or `.tsx` file is ever read, WHILE its own docstring cites the
    `<PKG>_FRAME_ANCESTORS` scar, which lived in the UI layer. A verifier proved the hole by
    adding `env.UI_TENANT_ORIGINS || "*"` to `lib/embed-policy.mjs`: a wildcard CORS allowlist
    reachable by emptying one variable, and it survived the whole gate, Python and node and tsc
    alike. The node-side scanner is the missing half; this asserts it exists, is wired into the
    command CI runs, and carries its own mutant proof, because a scanner nobody proved can fail
    is a green tick over an empty set.
    """
    guard = UI / "tests" / "three-state-env-reads.test.mjs"
    assert guard.exists(), "nothing scans ui/ for two-state environment reads"
    source = guard.read_text(encoding="utf-8")
    assert "TWO_STATE_READS_WITH_A_REASON" in source, (
        "the guard has no written-reason exemption list, so the only way past it is to delete it"
    )
    assert 'env.UI_TENANT_ORIGINS || "*"' in source, (
        "the guard carries no mutant, so nothing proves it can go red on the exact defect that "
        "survived the gate"
    )
    manifest = json.loads((UI / "package.json").read_text(encoding="utf-8"))
    assert "tests/*.test.mjs" in manifest["scripts"]["test"], (
        "the npm test script does not glob tests/, so the new guard may never run"
    )


@requires_ui
def test_the_service_credential_never_reaches_the_browser() -> None:
    """A token in a client component is a token in the bundle, which is a published token."""
    page = (UI / "app" / "page.tsx").read_text(encoding="utf-8")
    assert page.lstrip().startswith('"use client"'), "the console page is not a client component"
    for secret in ("AGENT_S2S_TOKEN", "process.env"):
        assert secret not in page, "a client component reads the server environment: " + secret


@requires_ui
def test_the_ui_documents_how_to_remove_itself() -> None:
    """Most catalog repos have no UI. Removing it must be cheaper than hand-building one."""
    assert "make drop-ui" in (UI / "README.md").read_text(encoding="utf-8")
    assert (REPO_ROOT / "scripts" / "drop_ui.py").exists()
    assert "drop-ui:" in (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
