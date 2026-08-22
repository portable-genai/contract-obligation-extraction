"""`config/settings.yaml` is the real binding map, and it cannot drift from the shipped default.

Two ways a settings file rots into decoration: it is never loaded, or it is loaded but says
something different from the code that also carries the same table. Both are tested here, plus
the three-state expansion rule, so a value an operator deliberately emptied never inherits the
default written in the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hex_service_kit.netdefaults import ConfiguredEmptyError

from contract_obligation_extraction.config import (
    DEFAULT_BINDINGS,
    KNOWN_PROFILES,
    Settings,
    _read_settings_file,
)

from tests import REPO_ROOT

_SETTINGS = REPO_ROOT / "config" / "settings.yaml"
_SETTINGS_ENV = "CONTRACT_SETTINGS"


def test_the_shipped_settings_file_exists_and_parses() -> None:
    assert _SETTINGS.is_file(), "config/settings.yaml is a required artifact"
    assert isinstance(yaml.safe_load(_SETTINGS.read_text(encoding="utf-8")), dict)


def test_the_files_adapter_block_matches_the_shipped_default_exactly() -> None:
    """One table, two homes, and they must agree; otherwise a binding can hide in one of them."""
    loaded = _read_settings_file(_SETTINGS)
    assert loaded["adapters"] == DEFAULT_BINDINGS


def test_every_port_in_the_file_binds_every_profile() -> None:
    loaded = _read_settings_file(_SETTINGS)
    for port, table in loaded["adapters"].items():
        assert set(table) == set(KNOWN_PROFILES), f"{port} does not bind every profile"


def test_settings_load_reads_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_SETTINGS_ENV, str(_SETTINGS))
    monkeypatch.delenv("GCP_REGION", raising=False)
    settings = Settings.load()
    assert settings.adapters == DEFAULT_BINDINGS
    assert settings.region == "asia-southeast1"


def test_a_named_settings_file_that_is_missing_is_a_boot_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Somebody named a file. Running on built-in defaults instead is a silent downgrade."""
    monkeypatch.setenv(_SETTINGS_ENV, str(REPO_ROOT / "config" / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        Settings.load()


def test_an_empty_settings_env_var_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_SETTINGS_ENV, "   ")
    with pytest.raises(ValueError, match=_SETTINGS_ENV):
        Settings.load()


def test_an_env_var_set_to_empty_does_not_inherit_the_files_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three-state expansion: unset takes the default, set-and-empty REFUSES.

    An emptied variable names nothing, so it inherits neither the file's default nor the empty
    string: for a base URL, an allowlist or a path the empty string is the permissive branch,
    and the loader is the last place that still knows a default was written. It raises at boot,
    where the operator who emptied it is still watching, rather than serving a posture nobody
    chose.
    """
    path = tmp_path / "settings.yaml"
    path.write_text("region: ${TEMPLATE_TEST_REGION:-fallback-region}\n", encoding="utf-8")

    monkeypatch.delenv("TEMPLATE_TEST_REGION", raising=False)
    assert _read_settings_file(path)["region"] == "fallback-region"

    monkeypatch.setenv("TEMPLATE_TEST_REGION", "   ")
    with pytest.raises(ConfiguredEmptyError, match="TEMPLATE_TEST_REGION"):
        _read_settings_file(path)

    monkeypatch.setenv("TEMPLATE_TEST_REGION", "chosen-region")
    assert _read_settings_file(path)["region"] == "chosen-region"


def test_a_partial_adapter_block_is_refused(tmp_path: Path) -> None:
    """A block that binds some ports would leave the rest on an invisible default."""
    path = tmp_path / "settings.yaml"
    path.write_text("adapters:\n  audit:\n    local: x:Y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="adapters"):
        Settings.load(path)
