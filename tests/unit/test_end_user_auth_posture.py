"""The exposure guard is derived from the IDENTITY BINDING, and from nothing else.

The defect this file is the standing guard for: the guard's ``unauthenticated`` argument used to
read

    bind_profile == local AND profile chosen AND CONTRACT_S2S_TOKEN unset

so SETTING the service-to-service secret switched the guard OFF. An adversarial verifier ran a
zero-hand-edit render bound to ``0.0.0.0`` with the profile chosen deliberately as ``local`` and
that secret set (an ordinary deployment shape) and, from a LAN peer with no Authorization header
and no ``X-Dev-Persona``, got ``/v1/personas`` with the full seeded persona list including the
approver's groups and tenant, and ``/v1/triage`` with a real escalated decision written to the
review outbox.

The cause is worth stating precisely, because widening the boolean would have hidden it rather
than fixed it: **the S2S token authenticates a calling SERVICE and authenticates NO END USER.**
The presence of a service credential is not evidence that end-user routes are authenticated. So
the guard now asks the only thing that knows: the identity adapter the active binding names,
which DECLARES whether it can produce a verified principal without trusting a header the client
wrote (``ports/identity.py``).

Three things are proved here, and the third is the one that stops the defect returning in a
different shape:

1. every shipped identity adapter declares, explicitly, what it does;
2. the declaration is what ``config.end_user_auth_kind`` reports, including when a settings file
   REBINDS the port (the documented on-premises path) and when the binding cannot be resolved
   at all, where it fails closed;
3. the guard's argument, expanded through the module constants it names, mentions no service
   credential anywhere. A scanner with a mutant that must go red, because the defect is
   exactly one indirection deep and passes any check that only reads one line.
"""

from __future__ import annotations

import ast

import pytest
from hex_service_kit.identity import RequestContext

from contract_obligation_extraction.adapters.gcp.identity import (
    IapIdentityAdapter,
)
from contract_obligation_extraction.adapters.local.identity import (
    LocalIdentityAdapter,
)
from contract_obligation_extraction.adapters.onprem.identity import (
    OnPremIdentityAdapter,
    OnPremIdentityUnimplementedError,
)
from contract_obligation_extraction.config import (
    DEFAULT_BINDINGS,
    KNOWN_PROFILES,
    Settings,
    end_user_auth_kind,
    identity_adapter_class,
)
from contract_obligation_extraction.ports.identity import (
    CLIENT_ASSERTED,
    END_USER_AUTH_ATTR,
    END_USER_AUTH_KINDS,
    UNIMPLEMENTED,
    VERIFIED,
    EndUserAuthUnavailableError,
    declared_end_user_auth,
)

from tests import REPO_ROOT
from tests.conftest import local_settings

#: This package's import root. Dotted targets below are built from it rather than written out,
#: so `ruff format` produces the same result whatever `package_name` a repo is rendered with: a
#: longer name inlined into an assignment wraps differently and would fail the rendered repo's
#: own format check on nothing but the length of its name.
_PKG = "contract_obligation_extraction"

_APP_MODULE = REPO_ROOT / "src" / _PKG / "api" / "app.py"

#: The guard call whose argument must never be derived from a credential.
_GUARD_CALL = "add_loopback_exposure_guard"

#: Anything naming a SERVICE credential. The guard bounds END-USER routes, so none of these may
#: appear anywhere in the expression that decides whether it is on, at any depth.
_CREDENTIAL_MARKERS: tuple[str, ...] = ("S2S", "TOKEN", "SECRET", "BEARER")


# --------------------------------------------------------------------------------------- #
# 1. Every shipped adapter declares what it does, explicitly.
# --------------------------------------------------------------------------------------- #
def test_the_seeded_persona_adapter_declares_that_the_client_asserts_its_identity() -> None:
    """A header the caller wrote is not authentication, and no other setting can make it one."""
    assert declared_end_user_auth(LocalIdentityAdapter) == CLIENT_ASSERTED


def test_the_iap_adapter_declares_that_it_verifies() -> None:
    """The one shipped adapter that checks a signature before reading a claim."""
    assert declared_end_user_auth(IapIdentityAdapter) == VERIFIED


def test_the_onprem_placeholder_declares_that_it_implements_nothing() -> None:
    assert declared_end_user_auth(OnPremIdentityAdapter) == UNIMPLEMENTED


@pytest.mark.parametrize("profile", KNOWN_PROFILES)
def test_every_bound_identity_adapter_declares_explicitly(profile: str) -> None:
    """A new adapter must SAY what it does; inheriting the safe default silently is not enough.

    The default exists so that an unannotated adapter cannot claim to verify anything. It is
    not a licence to leave the question unanswered: the answer decides whether the service may
    be reached from anywhere but loopback, and it belongs next to the code that resolves the
    principal, where a reviewer of that code will see it.
    """
    adapter = identity_adapter_class(local_settings(profile=profile))
    declared = [klass for klass in adapter.__mro__ if END_USER_AUTH_ATTR in vars(klass)]
    assert declared, (
        f"{adapter.__name__} (the {profile} identity binding) sets no {END_USER_AUTH_ATTR}. "
        f"Declare one of {sorted(END_USER_AUTH_KINDS)} on the class: the exposure guard reads "
        "it, and silence is read as client-asserted."
    )
    assert declared_end_user_auth(adapter) in END_USER_AUTH_KINDS


# --------------------------------------------------------------------------------------- #
# 2. The declaration is what the posture reports, including through a rebinding.
# --------------------------------------------------------------------------------------- #
class _UndeclaredAdapter:
    """An adapter that says nothing at all."""


class _MisdeclaredAdapter:
    """An adapter whose declaration is a typo, which must not read as a verification claim."""

    end_user_auth = "Verified"


@pytest.mark.parametrize("adapter", [_UndeclaredAdapter, _MisdeclaredAdapter, object()])
def test_silence_and_typos_are_read_as_client_asserted(adapter: object) -> None:
    """The fail-closed default, in the only direction that matters: never VERIFIED."""
    assert declared_end_user_auth(adapter) == CLIENT_ASSERTED


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("local", CLIENT_ASSERTED), ("gcp", VERIFIED), ("onprem", UNIMPLEMENTED)],
)
def test_the_posture_follows_the_profile_binding(profile: str, expected: str) -> None:
    assert end_user_auth_kind(local_settings(profile=profile)) == expected


def test_the_posture_follows_a_REBOUND_identity_port_not_the_profile_name() -> None:
    """The on-premises migration path: bind a real IdP adapter and the posture changes with it.

    This is why the guard reads the BINDING rather than the profile string. A client who wires
    their own verifying adapter under ``onprem`` has an authenticated service, and a guard that
    keyed off the word "onprem" would confine it to loopback forever with no way out but the
    insecure-demo opt-out.
    """
    rebound = {port: dict(table) for port, table in DEFAULT_BINDINGS.items()}
    rebound["identity"]["onprem"] = f"{_PKG}.adapters.gcp.identity:IapIdentityAdapter"
    assert end_user_auth_kind(local_settings(profile="onprem", adapters=rebound)) == VERIFIED


def test_an_unresolvable_binding_fails_CLOSED_rather_than_raising_past_the_guard() -> None:
    """A guard that switches off because a lookup raised is a guard that fails open.

    The same failure is still loud: the container resolves the identical binding on the first
    request and raises there, where it is a visible 500 rather than a silent relaxation.
    """
    broken = {port: dict(table) for port, table in DEFAULT_BINDINGS.items()}
    broken["identity"]["local"] = f"{_PKG}.nope:Missing"
    settings = local_settings(adapters=broken)
    assert end_user_auth_kind(settings) == CLIENT_ASSERTED
    with pytest.raises(ModuleNotFoundError):
        identity_adapter_class(settings)


def test_the_declaration_is_readable_without_constructing_the_adapter() -> None:
    """The seeded-persona adapter REFUSES to construct under an inherited profile.

    A posture computed from an instance would therefore be unobtainable in one of the exact
    cases it has to describe, so the whole derivation reads the class.
    """
    inherited = Settings(profile="local", profile_explicit=False)
    with pytest.raises(EndUserAuthUnavailableError):
        LocalIdentityAdapter(inherited)
    assert end_user_auth_kind(inherited) == CLIENT_ASSERTED


# --------------------------------------------------------------------------------------- #
# The on-premises placeholder refuses with a status and a reason, not a bare 500.
# --------------------------------------------------------------------------------------- #
def test_the_onprem_placeholder_raises_a_refusal_with_a_status_and_a_reason() -> None:
    """Two ancestries, both load-bearing; the message names what to bind and where."""
    adapter = OnPremIdentityAdapter(local_settings(profile="onprem"))
    with pytest.raises(OnPremIdentityUnimplementedError) as caught:
        adapter.resolve(RequestContext())
    error = caught.value
    assert isinstance(error, EndUserAuthUnavailableError), "must report a status and a reason"
    assert isinstance(error, NotImplementedError), "the exit family's uniform refusal stands"
    assert error.http_status == 501, "no credential would have helped, so 401 would be a lie"
    assert "docs/onprem-migration.md" in str(error)


# --------------------------------------------------------------------------------------- #
# 3. The guard's argument names no credential, at any depth.
# --------------------------------------------------------------------------------------- #
def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = <expr>`` assignments, as source text."""
    found: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                found[target.id] = ast.unparse(node.value)
    return found


def guard_posture_source(source: str) -> str:
    """Everything the exposure guard's ``unauthenticated`` argument reaches, as one blob.

    Public, and transitive on purpose. The defect is one indirection deep: the call
    site read ``unauthenticated=_UNCONSENTED or _ZERO_SECRET_LOCAL`` and the credential was
    named in ``_ZERO_SECRET_LOCAL`` a few lines above. A check that only read the call site
    would have passed it.
    """
    tree = ast.parse(source)
    constants = _module_constants(tree)
    expressions: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(_GUARD_CALL):
            expressions += [
                ast.unparse(kw.value) for kw in node.keywords if kw.arg == "unauthenticated"
            ]
    assert expressions, f"no {_GUARD_CALL}(unauthenticated=...) call found"
    seen: set[str] = set()
    reached = list(expressions)
    pending = list(expressions)
    while pending:
        for name_node in ast.walk(ast.parse(pending.pop(), mode="eval")):
            if isinstance(name_node, ast.Name) and name_node.id not in seen:
                seen.add(name_node.id)
                if name_node.id in constants:
                    reached.append(constants[name_node.id])
                    pending.append(constants[name_node.id])
    return "\n".join(reached + sorted(seen))


def test_the_exposure_guard_reads_no_service_credential() -> None:
    """The defect, stated as a rule: a service credential may not decide an end-user bound."""
    reached = guard_posture_source(_APP_MODULE.read_text(encoding="utf-8")).upper()
    offenders = [marker for marker in _CREDENTIAL_MARKERS if marker in reached]
    assert offenders == [], (
        f"the exposure guard's posture reaches {offenders}. It bounds END-USER routes, and a "
        "service-to-service credential authenticates a calling SERVICE and no end user, so its "
        "presence is not evidence that anything is authenticated. Derive the posture from the "
        "identity binding (config.end_user_auth_kind) instead."
    )


def test_the_exposure_guard_is_derived_from_the_identity_binding() -> None:
    """Not merely "no credential": the posture must come from the thing that actually knows."""
    reached = guard_posture_source(_APP_MODULE.read_text(encoding="utf-8"))
    assert "end_user_auth_kind" in reached, (
        "the guard no longer reads the identity binding, so nothing checks whether an end user "
        "can be authenticated at all"
    )


#: The defect exactly as it was written, one indirection deep. A scanner nobody proved can find
#: anything is a green tick over an empty set.
_MUTANT = (
    "_TOKEN_ENV = 'PREFIX_S2S_TOKEN'\n"
    "_UNCONSENTED = not _CHOICE.explicit\n"
    "_ZERO_SECRET_LOCAL = (\n"
    "    _CHOICE.bind_profile == LOCAL_PROFILE\n"
    "    and _CHOICE.service_auth_configured\n"
    "    and not read_env_setting(_TOKEN_ENV).has_value\n"
    ")\n"
    "add_loopback_exposure_guard(\n"
    "    app, unauthenticated=_UNCONSENTED or _ZERO_SECRET_LOCAL, posture=_EXPOSURE\n"
    ")\n"
)


def test_the_scan_finds_the_defect_it_was_written_for() -> None:
    reached = guard_posture_source(_MUTANT).upper()
    caught = {marker for marker in _CREDENTIAL_MARKERS if marker in reached}
    assert caught == {"S2S", "TOKEN", "SECRET"}, (
        "the scan no longer finds the credential in the expression the defect was written as, "
        "so a green result from it means nothing"
    )
