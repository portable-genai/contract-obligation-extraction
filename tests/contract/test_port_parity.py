"""Structural parity: every port binds and conforms in every profile, with NO cloud SDK.

This is the hexagon's load-bearing contract test: switching the whole stack is a one-line profile
change with no domain edits, and the SDK-free families construct with no cloud SDK importable
(the portability proof, P-02).

**The drift guard is the part that keeps the rest honest.** A port lives in five places at once:
the Protocol map, the shipped binding table, the settings file, the container accessor and the
canonical-call table this suite drives. Four of those five can be satisfied while the fifth is
missing, and the result is a port with ZERO enforcement and a green build. So the guard is set
equality across all five, in both directions, rather than a one-way "everything declared is
bound" check that an unregistered port passes silently.
"""

from __future__ import annotations

import functools
import importlib
import subprocess
import sys

import pytest
import yaml

from contract_obligation_extraction.config import (
    DEFAULT_BINDINGS,
    KNOWN_PROFILES,
    Container,
    Settings,
    build_container,
)
from contract_obligation_extraction.ports import (
    PORT_PROTOCOLS,
)

from .canonical import CANONICAL_CALLS
from tests import REPO_ROOT
from tests.conftest import local_settings

_SETTINGS_FILE = REPO_ROOT / "config" / "settings.yaml"

#: Profiles that must construct with the managed SDKs unimportable. That is every profile: the
#: managed adapters keep their SDK imports INSIDE the method precisely so binding them offline
#: works, which is what lets one process import the whole adapter set.
SDK_FREE_PROFILES = KNOWN_PROFILES


def _settings(profile: str) -> Settings:
    return local_settings(profile=profile)


def _container_ports() -> set[str]:
    """The ports the Container actually exposes (one ``cached_property`` per port)."""
    return {
        name
        for name, value in vars(Container).items()
        if isinstance(value, functools.cached_property)
    }


def _settings_file_ports() -> set[str]:
    loaded = yaml.safe_load(_SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    return set(loaded.get("adapters") or {})


def _protocol_members(protocol: type) -> set[str]:
    """The attribute names a Protocol declares (methods + properties), no dunders."""
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    return {name for name in members if not name.startswith("_")}


# --------------------------------------------------------------------------- #
# The drift guard: five homes, one port set
# --------------------------------------------------------------------------- #
def test_every_home_of_the_port_set_agrees_exactly() -> None:
    homes = {
        "ports/__init__.py PORT_PROTOCOLS": set(PORT_PROTOCOLS),
        "config.py DEFAULT_BINDINGS": set(DEFAULT_BINDINGS),
        "config/settings.yaml adapters": _settings_file_ports(),
        "config.py Container accessors": _container_ports(),
        "tests/contract/canonical.py CANONICAL_CALLS": set(CANONICAL_CALLS),
    }
    expected = set(PORT_PROTOCOLS)
    mismatched = {
        name: sorted(ports ^ expected) for name, ports in homes.items() if ports != expected
    }
    assert not mismatched, (
        "the port set has drifted between the places a port must be registered "
        f"(symmetric difference against PORT_PROTOCOLS): {mismatched}. "
        "See the 'adding a new port' walkthrough in CONTRIBUTING.md for the full touch list."
    )


@pytest.mark.parametrize("port", sorted(DEFAULT_BINDINGS))
def test_every_port_binds_every_known_profile(port: str) -> None:
    assert set(DEFAULT_BINDINGS[port]) == set(KNOWN_PROFILES)


# --------------------------------------------------------------------------- #
# Conformance: the binding resolves, constructs and satisfies its Protocol
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", KNOWN_PROFILES)
def test_every_port_binds_and_conforms(profile: str) -> None:
    container = build_container(_settings(profile))
    for port, protocol in PORT_PROTOCOLS.items():
        adapter = getattr(container, port)
        assert isinstance(adapter, protocol), f"{port} adapter does not satisfy its Protocol"


@pytest.mark.parametrize("profile", KNOWN_PROFILES)
@pytest.mark.parametrize("port", sorted(PORT_PROTOCOLS))
def test_every_protocol_member_is_declared_on_the_adapter_class(profile: str, port: str) -> None:
    """Check the CLASS, not the instance: a placeholder property getter may raise."""
    adapter = getattr(build_container(_settings(profile)), port)
    declared: set[str] = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in _protocol_members(PORT_PROTOCOLS[port]):
        assert member in declared, (
            f"{type(adapter).__name__} is missing '{member}' of "
            f"{PORT_PROTOCOLS[port].__name__} in the {profile} profile"
        )


@pytest.mark.parametrize("port", sorted(DEFAULT_BINDINGS))
def test_adapter_constructs_with_a_single_settings_argument(port: str) -> None:
    """One adapter constructor shape, so the container never needs per-port wiring."""
    for profile in KNOWN_PROFILES:
        settings = _settings(profile)
        module_path, _, class_name = DEFAULT_BINDINGS[port][profile].partition(":")
        adapter_cls = getattr(importlib.import_module(module_path), class_name)
        assert adapter_cls(settings) is not None


# --------------------------------------------------------------------------- #
# The portability proof: no cloud SDK, at all, for any profile
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
def test_every_profile_constructs_with_no_cloud_sdk_importable(profile: str) -> None:
    """Not "no SDK installed on this machine": a whole interpreter where it cannot be imported.

    Proving it by absence would make the claim depend on the developer's environment: a machine
    with the SDK installed would pass while hiding an eager import that breaks the offline gate
    everywhere else. The probe runs in a fresh process (see ``_sdk_free_probe``).
    """
    completed = subprocess.run(
        [sys.executable, "-m", "tests.contract._sdk_free_probe", profile],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert completed.returncode == 0, (
        f"the {profile} profile could not be built with the cloud SDKs blocked:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_the_blocked_sdk_harness_actually_blocks(no_cloud_sdk: None) -> None:
    """A harness that quietly stopped blocking would make the proof above vacuous."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("google.cloud.logging")
