"""The three-state environment read, in the one shape every package in this catalog needs.

``hex_service_kit.netdefaults.read_env_setting`` resolves the three states; what recurs here is
the decision that follows them. Writing those decisions once keeps every adapter honest, because
the tempting shorthand is ``os.environ.get(name, default)``, and that hands a variable an operator
deliberately emptied exactly what it hands one nobody set.

For a base URL the difference is not academic. The defaults are ``http://localhost:<port>``, so an
emptied ``HRZ_AUDIT_URL`` in a deployed environment would not fail: it would silently point the
audit client at the pod's own loopback, where nothing is listening or, worse, something else is.
Refusing at construction is the loud failure that an emptied value deserves.

Four decisions live here, and this file is byte-identical in every repo whether or not a given repo
calls all four. A helper a repo does not call costs nothing and is not a licence to write a fifth
shape locally; divergence is the thing this file exists to prevent.

Reads whose closed direction is the SAME for unset and emptied do not belong here: they call
``read_env_setting(name).value`` directly and let both states land on the empty string, which is
the refusal. The IAP audience is the standing example.
"""

from __future__ import annotations

from hex_service_kit.netdefaults import ConfiguredEmptyError, EnvSetting, read_env_setting

__all__ = [
    "ConfiguredEmptyError",
    "EnvSetting",
    "boolean_setting",
    "optional_setting",
    "read_env_setting",
    "required_setting",
    "setting_or_default",
]

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def setting_or_default(name: str, default: str) -> str:
    """Resolve ``name`` in three states: unset takes ``default``, EMPTIED refuses, a value wins.

    Raises:
        ConfiguredEmptyError: when the variable is present but empty or whitespace. An operator
            who emptied it expressed an intent, and it names nothing, so it must not inherit the
            documented default.
    """
    setting = read_env_setting(name)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{name} is set to an empty value, which names nothing. Unset it to take the "
            f"documented default ({default!r}), or give it a value."
        )
    return setting.value if setting.has_value else default


def optional_setting(name: str) -> str | None:
    """Resolve a setting whose absence is legitimate: unset is ``None``, EMPTIED refuses."""
    setting = read_env_setting(name)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{name} is set to an empty value, which names nothing. Unset it to leave the "
            "setting absent, or give it a value."
        )
    return setting.value if setting.has_value else None


def required_setting(name: str) -> str:
    """Resolve a setting that must be configured: both unset and EMPTIED refuse."""
    value = optional_setting(name)
    if value is None:
        raise ConfiguredEmptyError(f"{name} is required but is not configured.")
    return value


def boolean_setting(name: str, *, default: bool = False) -> bool:
    """Resolve a boolean without treating every non-empty string, including ``false``, as true."""
    setting = read_env_setting(name)
    if setting.is_unset:
        return default
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{name} is set to an empty value, which names nothing. Unset it to take the "
            f"documented default ({default!r}), or set it to true or false."
        )
    value = setting.value.casefold()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be one of {sorted(_TRUE | _FALSE)}, got {setting.value!r}")
