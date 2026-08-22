"""The profile has ONE source of truth, it is three-state, and a bad value dies AT IMPORT.

Guarding a fail-open profile read in the identity adapter alone leaves it open anyway, because
`api/app.py` re-derives the same decision with its own raw fallback. That is the shape of the
bug: a permissive default gets reintroduced one module at a time, and every individual
reintroduction looks harmless. So a drift guard is part of the defence rather than a nicety,
and a rendered repo is born with it.

Three states of one variable, resolved into four outcomes and never folded together:

* UNSET means NOBODY CHOSE. The adapter family is still `local` (the alternative is importing
  cloud SDKs that are not installed), but `explicit` is False, so the seeded-persona adapter
  refuses, no S2S scheme is selected, and every relaxation sees `UNCONSENTED_PROFILE`;
* SET AND EMPTY raises `ConfiguredEmptyError`. It must never inherit the unset default: a
  variable an operator deliberately emptied is an expressed intent that names no profile;
* SET AND UNKNOWN raises, including a merely mis-capitalised `Local` / `LOCAL` / `GCP`;
* only SET AND VALID selects an adapter family.

Asserting the opposite of the first two, with a
`test_an_absent_or_blank_variable_is_the_offline_default` requiring `resolve_profile({})`,
`resolve_profile({VAR: ""})` and `resolve_profile({VAR: "   "})` to be indistinguishable from a
chosen `local`, would PIN the fail-open: a repo owner who closed the resolver would break a
green test and could reasonably revert. The three states are asserted separately
below, so this file is the standing regression guard rather than a guard on the defect.

The generalised form of the same drift guard, covering every security-relevant environment read
rather than only the profile, lives in `tests/unit/test_three_state_env_reads.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from hex_service_kit.netdefaults import ConfiguredEmptyError

from contract_obligation_extraction.config import (
    KNOWN_PROFILES,
    LOCAL_PROFILE,
    PROFILE_CHOICE,
    UNCONSENTED_PROFILE,
    Settings,
    resolve_profile,
)

from tests import REPO_ROOT
from tests.unit.test_three_state_env_reads import environment_reads, scanned_sources

_PROFILE_ENV = "CONTRACT_PROFILE"
_PACKAGE = "contract_obligation_extraction"
_PACKAGE_ROOT = REPO_ROOT / "src" / _PACKAGE
_CONFIG_MODULE = _PACKAGE_ROOT / "config.py"

#: What the subprocess prints. A constant, so the line that builds the snippet stays short
#: whatever the rendered package name is (`ruff format` must not depend on it).
_REPORT = "print(c.PROFILE_CHOICE.profile, c.PROFILE_CHOICE.explicit)"

#: Any environment read whose variable name mentions a profile. Deliberately broader than the
#: exact variable: a module that invented its own ``SOMETHING_PROFILE`` would be the same defect.
_ENV_PROFILE_READ = re.compile(r"(os\.environ|os\.getenv)[^\n]*PROFILE")


def _package_sources() -> list[Path]:
    return sorted(p for p in _PACKAGE_ROOT.rglob("*.py") if p != _CONFIG_MODULE)


def test_only_the_resolver_reads_a_profile_variable_from_the_environment() -> None:
    offenders = []
    for path in _package_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _ENV_PROFILE_READ.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        "these modules re-derive the profile instead of calling config.resolve_profile, so a "
        "permissive default can be reintroduced one module at a time:\n" + "\n".join(offenders)
    )


def test_no_shipped_module_outside_config_reads_a_profile_variable_at_all() -> None:
    """The same rule again, from the syntax tree rather than from a line of text.

    The regex above reads one line at a time, so a read split across two lines slips past it,
    and it scans only ``src/``. This walks the AST of everything that ships (``src/``,
    ``scripts/``, ``eval/``) and looks at the NAME each environment read names, whether that is
    a literal or a module constant.

    MENTIONING the variable is fine and wanted: a refusal that does not name the variable an
    operator must set is a refusal nobody can act on, and ``api/app.py`` and
    ``adapters/local/identity.py`` both say the name out loud in their error messages. Reading
    it anywhere but ``config.resolve_profile`` is the defect.
    """
    offenders = []
    for path in scanned_sources():
        if path.resolve() == _CONFIG_MODULE.resolve():
            continue
        for line, name, _ in environment_reads(path):
            if "PROFILE" in name.upper():
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}: reads {name}")
    assert offenders == [], (
        f"{offenders} read a profile variable directly. Import resolve_profile from config.py "
        "instead, so there is exactly one place the deployment posture is decided."
    )


# --------------------------------------------------------------------------------------- #
# The three states, asserted SEPARATELY. This is the block that pins the defect.
# --------------------------------------------------------------------------------------- #
def test_an_absent_variable_is_no_choice_rather_than_a_chosen_local() -> None:
    """UNSET is carried forward as its own state, not folded into a deliberate ``local``."""
    choice = resolve_profile({})
    assert choice.profile == LOCAL_PROFILE, "the SDK-free family is still what binds"
    assert choice.explicit is False, "but nobody chose it, and that must remain visible"
    assert choice.service_auth_configured is False


@pytest.mark.parametrize("raw", ["", "   ", "\n", "\t "])
def test_a_variable_set_to_empty_refuses_rather_than_inheriting_the_unset_default(
    raw: str,
) -> None:
    """SET AND EMPTY is an expressed intent that names no profile, so it is refused.

    The old assertion here was that these were the offline default, which is precisely the
    fail-open: an operator (or a config map, or a templated deployment) that emptied the
    variable got the most permissive posture the service has.
    """
    with pytest.raises(ConfiguredEmptyError, match=_PROFILE_ENV):
        resolve_profile({_PROFILE_ENV: raw})


@pytest.mark.parametrize("raw", ["bogus", "Local", "LOCAL", "GCP", "on-prem"])
def test_an_unknown_or_miscapitalised_value_is_refused(raw: str) -> None:
    """A typo must not silently downgrade the posture, nor fall through to another family."""
    with pytest.raises(ValueError, match=_PROFILE_ENV):
        resolve_profile({_PROFILE_ENV: raw})


def test_a_deliberate_profile_is_carried_through_unchanged() -> None:
    choice = resolve_profile({_PROFILE_ENV: "gcp"})
    assert (choice.profile, choice.explicit) == ("gcp", True)
    assert choice.exposure_profile == "gcp"
    assert choice.bind_profile == "gcp"
    assert choice.service_auth_configured is True


def test_every_known_profile_is_actually_selectable() -> None:
    for profile in KNOWN_PROFILES:
        assert resolve_profile({_PROFILE_ENV: profile}).profile == profile


# --------------------------------------------------------------------------------------- #
# The two derived postures fail closed in OPPOSITE directions.
# --------------------------------------------------------------------------------------- #
def test_an_unconsented_run_is_not_the_local_profile_for_any_relaxation() -> None:
    """CORS, the dev-persona header and HSTS all key off this, and none may see ``local``."""
    choice = resolve_profile({})
    assert choice.exposure_profile == UNCONSENTED_PROFILE
    assert choice.exposure_profile != LOCAL_PROFILE
    assert UNCONSENTED_PROFILE not in KNOWN_PROFILES


def test_an_unconsented_run_still_binds_loopback() -> None:
    """The bind guard is a RESTRICTION, where ``local`` is the confined case, not the open one."""
    assert resolve_profile({}).bind_profile == LOCAL_PROFILE


def test_the_two_derived_postures_disagree_exactly_when_nobody_chose() -> None:
    """One string cannot serve both directions; that they differ HERE is the whole mechanism."""
    unconsented = resolve_profile({})
    assert unconsented.exposure_profile != unconsented.bind_profile
    for profile in KNOWN_PROFILES:
        chosen = resolve_profile({_PROFILE_ENV: profile})
        assert chosen.exposure_profile == chosen.bind_profile == profile


def test_settings_carry_the_deliberateness_and_direct_construction_is_deliberate() -> None:
    """Naming a profile in code IS a choice; only the environment read can be unconsented."""
    assert Settings(profile=LOCAL_PROFILE).profile_explicit is True


@pytest.mark.parametrize("raw", ["bogus", "Local", "GCP"])
def test_settings_refuses_the_same_values_when_constructed_directly(raw: str) -> None:
    with pytest.raises(ValueError, match="not a known profile"):
        Settings(profile=raw)


def test_the_module_level_resolution_agrees_with_the_resolver() -> None:
    """``PROFILE_CHOICE`` is what made the import fail or succeed; it is not a second read."""
    assert resolve_profile() == PROFILE_CHOICE


# --------------------------------------------------------------------------------------- #
# ...and all of it happens at IMPORT, in a real interpreter.
# --------------------------------------------------------------------------------------- #
def _import_config(value: str | None) -> subprocess.CompletedProcess[str]:
    """Import the config module in a FRESH interpreter under the given profile value."""
    env = dict(os.environ)
    if value is None:
        env.pop(_PROFILE_ENV, None)
    else:
        env[_PROFILE_ENV] = value
    snippet = f"import {_PACKAGE}.config as c; {_REPORT}"
    return subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        check=False,
    )


@pytest.mark.parametrize("raw", ["bogus", "Local", "LOCAL", "GCP"])
def test_a_bad_profile_kills_the_process_at_import_not_at_first_request(raw: str) -> None:
    """Import time, in a real interpreter: nothing downstream gets the chance to run."""
    completed = _import_config(raw)
    assert completed.returncode != 0, f"import with {raw!r} succeeded: {completed.stdout}"
    assert _PROFILE_ENV in completed.stderr
    assert "not a known profile" in completed.stderr


@pytest.mark.parametrize("raw", ["", "   "])
def test_an_emptied_profile_also_kills_the_process_at_import(raw: str) -> None:
    completed = _import_config(raw)
    assert completed.returncode != 0, f"import with {raw!r} succeeded: {completed.stdout}"
    assert "ConfiguredEmptyError" in completed.stderr
    assert _PROFILE_ENV in completed.stderr


def test_an_unset_profile_imports_but_records_that_nobody_chose() -> None:
    completed = _import_config(None)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == [LOCAL_PROFILE, "False"]
