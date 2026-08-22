"""The IAP verifier, branch by branch, with NO cloud SDK: the adapter's own half of the claim.

This adapter is the one that declares
``VERIFIED`` (see ``ports/identity.py``), and that declaration is the
single flag the exposure guard reads before it lets the process bind every interface. Leaving
it the one adapter with NO tests at all is how three defects sit in three lines of it while the
whole gate stays green: ``resolve`` carrying ``# pragma: no cover - needs live GCP`` and a suite
exercising only the header-absent branch prove nothing about the branch that matters.

    claims = id_token.verify_token(assertion, ga_requests.Request())

1. **no ``audience=``.** google-auth documents ``audience=None`` as "the audience is not
   verified". ANY Google-signed OIDC ID token, from any project or any application, was accepted
   and its ``email`` became the verified subject.
2. **no ``certs_url=``.** The default is the OAuth2 federated key set, not the set IAP signs
   with, so the signature check was against the wrong keys.
3. **no ``try``.** ``google.auth.exceptions.MalformedError`` is a ``ValueError``, not an
   ``IdentityError``, so it escaped ``get_principal`` and FastAPI answered a bare 500. Proved
   over the wire: ``X-Goog-IAP-JWT-Assertion: not-a-jwt`` from a LAN peer, twice, once with
   google-auth installed and once without.

Everything here runs with the google modules FAKED or BLOCKED, so it needs no cloud SDK, no
project and no network, and it runs in every rendered repo's ``make gate``. What a fake verifier
cannot prove is that the REAL verifier rejects a wrong audience, an expired token or a signature
from the wrong key; that is ``tests/unit/test_iap_crypto_matrix.py``, which mints assertions with
a locally generated key and runs google-auth over them for real.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit.identity import IdentityError

from contract_obligation_extraction.adapters.gcp.identity import (
    _AUDIENCE_ENV,
    _IAP_ASSERTION_HEADER,
    _IAP_ISSUER,
    _IAP_KEYS_URL,
    IapAudienceUnconfiguredError,
    IapIdentityAdapter,
    IapVerifierUnavailableError,
)
from contract_obligation_extraction.config import Settings
from contract_obligation_extraction.ports.identity import (
    VERIFIED,
    EndUserAuthUnavailableError,
    declared_end_user_auth,
)

from tests.conftest import is_blocked_sdk

#: A configured audience: the IAP-protected resource, obviously fictional.
AUDIENCE = "/projects/000000000000/global/backendServices/1111111111111111111"

#: The claim set a real IAP assertion carries once verified.
GOOD_CLAIMS: dict[str, Any] = {
    "iss": _IAP_ISSUER,
    "sub": "accounts.google.com:100000000000000000001",
    "email": "analyst@bank.example",
    "hd": "bank.example",
    # `exp` is what makes a captured assertion stop working. verify_token checks it, and
    # the claim pin requires its PRESENCE too: a token with no exp is one that never expires.
    "exp": 1_900_000_000,
}

_PROFILE_ENV = "CONTRACT_PROFILE"
_SETTINGS_ENV = "CONTRACT_SETTINGS"

#: The API module, named once so no line's length depends on the rendered package name.
_API_MODULE = "contract_obligation_extraction.api.app"


# --------------------------------------------------------------------------------------- #
# A fake google-auth: it records exactly what the adapter passed, and raises what we tell it.
# --------------------------------------------------------------------------------------- #
def signed_assertion(alg: str = "RS256") -> str:
    """A structurally real compact JWS, because the algorithm pin reads the JOSE header.

    These fixtures used the literal `"signed.iap.jwt"`, which was fine while nothing looked at
    the token before the (stubbed) verifier did. `require_pinned_algorithm` looks, so a fixture
    that is not a JWS is now refused before it reaches the stub. Making the fixture real is the
    correct repair rather than relaxing the pin: a test whose token could never exist proves
    nothing about a token that can. Nothing here is signed; only the header is ever parsed.
    """
    import base64
    import json as _json

    header = (
        base64.urlsafe_b64encode(_json.dumps({"alg": alg, "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = base64.urlsafe_b64encode(b'{"sub":"1"}').decode().rstrip("=")
    return f"{header}.{payload}.c2ln"


def install_fake_google(
    monkeypatch: pytest.MonkeyPatch,
    outcome: dict[str, Any] | Exception,
    captured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Put a fake ``google.oauth2.id_token`` on ``sys.modules`` and return the capture dict.

    The signature is keyword-only for ``audience`` and ``certs_url`` DELIBERATELY: the defect
    was calling ``verify_token`` without either, and a fake that accepted them positionally (or
    defaulted them) would still be satisfied by the defective call.
    """
    seen: dict[str, Any] = captured if captured is not None else {}

    def verify_token(
        assertion: str,
        request: object,
        *,
        audience: str,
        certs_url: str,
    ) -> dict[str, Any]:
        seen.update(assertion=assertion, request=request, audience=audience, certs_url=certs_url)
        if isinstance(outcome, Exception):
            raise outcome
        claims = dict(outcome)
        # A real verifier only ever returns claims whose `aud` is the audience it was asked to
        # check; it refuses everything else. The fixture echoes it for the same reason the claim
        # set carries `exp`: a stub that describes a token no deployment issues tests a contract
        # nobody ships. A test that deliberately supplies a MISMATCHED `aud` keeps its own value.
        claims.setdefault("aud", audience)
        return claims

    google = ModuleType("google")
    auth = ModuleType("google.auth")
    transport = ModuleType("google.auth.transport")
    oauth2 = ModuleType("google.oauth2")
    id_token = ModuleType("google.oauth2.id_token")

    class Request:
        """Stands in for ``google.auth.transport.requests.Request``; never called."""

    transport.requests = SimpleNamespace(Request=Request)  # type: ignore[attr-defined]
    id_token.verify_token = verify_token  # type: ignore[attr-defined]
    google.auth = auth  # type: ignore[attr-defined]
    google.oauth2 = oauth2  # type: ignore[attr-defined]
    auth.transport = transport  # type: ignore[attr-defined]
    oauth2.id_token = id_token  # type: ignore[attr-defined]
    for name, module in {
        "google": google,
        "google.auth": auth,
        "google.auth.transport": transport,
        "google.auth.transport.requests": transport.requests,  # type: ignore[attr-defined]
        "google.oauth2": oauth2,
        "google.oauth2.id_token": id_token,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return seen


def adapter(audience: str = AUDIENCE) -> IapIdentityAdapter:
    return IapIdentityAdapter(Settings(profile="gcp", iap_audience=audience))


def context(assertion: str | None = signed_assertion()) -> Any:
    from hex_service_kit.identity import RequestContext

    return RequestContext(headers={} if assertion is None else {_IAP_ASSERTION_HEADER: assertion})


# --------------------------------------------------------------------------------------- #
# 1. The audience is verified, it is configuration, and it is three-state.
# --------------------------------------------------------------------------------------- #
def test_the_adapter_declares_that_it_verifies() -> None:
    """The claim the exposure guard cashes. Everything below is that claim being earned."""
    assert declared_end_user_auth(IapIdentityAdapter) == VERIFIED


@pytest.mark.parametrize("audience", ["", "   ", "\t\n"])
def test_an_unset_or_blank_audience_refuses_instead_of_verifying_without_one(
    audience: str,
) -> None:
    """The whole point: there is no verify-without-an-audience path to fall into.

    Set-and-blank is the state a deployment template produces when a substitution is missing.
    It is truthy, so an unstripped read would hand ``"   "`` to the verifier as the expected
    audience: configured-looking, and matching nothing.
    """
    with pytest.raises(IapAudienceUnconfiguredError) as caught:
        adapter(audience).resolve(context())
    assert _AUDIENCE_ENV in str(caught.value)
    assert caught.value.http_status == 503, "no credential would have helped, so 401 is a lie"
    assert isinstance(caught.value, EndUserAuthUnavailableError)


def test_the_unconfigured_refusal_happens_before_the_sdk_is_even_reached(
    no_cloud_sdk: None,
) -> None:
    """Proved by making ``google`` UNIMPORTABLE: nothing about this refusal can depend on it.

    The check is first for a reason. A refusal that ran after the lazy import would depend on
    the SDK being installed, and a refusal that ran after the header read would depend on what
    the caller presented; an unconfigured deployment must refuse on its own configuration alone.
    """
    assert is_blocked_sdk("google.oauth2.id_token"), "the SDK block is not in force"
    with pytest.raises(IapAudienceUnconfiguredError):
        adapter("").resolve(context())


@pytest.mark.parametrize("assertion", [None, "", "   "])
def test_a_missing_or_blank_assertion_header_is_refused_without_the_sdk(
    assertion: str | None, no_cloud_sdk: None
) -> None:
    """A request that did not pass through IAP is refused before any verifier exists."""
    with pytest.raises(IdentityError) as caught:
        adapter().resolve(context(assertion))
    assert "missing IAP assertion header" in str(caught.value)
    assert not isinstance(caught.value, EndUserAuthUnavailableError), (
        "THIS caller failed to authenticate; the deployment is fine, so this is a plain 401"
    )


# --------------------------------------------------------------------------------------- #
# 2. The call contract: the audience and IAP's own key set are both passed, every time.
# --------------------------------------------------------------------------------------- #
def test_the_verifier_is_called_with_the_audience_and_the_iap_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact refutation, as a contract. Both arguments were absent; both are asserted."""
    captured = install_fake_google(monkeypatch, GOOD_CLAIMS)

    principal = adapter().resolve(context())

    assert captured["audience"] == AUDIENCE, "audience=None means the audience is NOT verified"
    assert captured["certs_url"] == _IAP_KEYS_URL, "the default key set is not IAP's key set"
    assert captured["assertion"] == signed_assertion()
    assert principal.subject == "analyst@bank.example"
    assert principal.tenant == "bank.example"
    assert principal.source == "gcp-iap"
    assert principal.actor == principal.subject


def test_the_pinned_key_set_is_iaps_published_one() -> None:
    """A literal worth asserting: a typo here silently verifies against the wrong keys."""
    assert _IAP_KEYS_URL == "https://www.gstatic.com/iap/verify/public_key"
    assert _IAP_ISSUER == "https://cloud.google.com/iap"


def test_the_configured_audience_is_what_reaches_the_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuration, not a literal: a different deployment verifies a different resource."""
    other = "/projects/999999999999/global/backendServices/2222222222222222222"
    captured = install_fake_google(monkeypatch, GOOD_CLAIMS)
    adapter(other).resolve(context())
    assert captured["audience"] == other


def test_a_surrounding_whitespace_only_audience_never_reaches_the_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = install_fake_google(monkeypatch, GOOD_CLAIMS)
    with pytest.raises(IapAudienceUnconfiguredError):
        adapter("  \t ").resolve(context())
    assert captured == {}, "the verifier was called with a blank audience"


# --------------------------------------------------------------------------------------- #
# 3. A crash is not a refusal. Every failure of the managed verifier becomes an IdentityError.
# --------------------------------------------------------------------------------------- #
class _MalformedError(ValueError):
    """Shaped like ``google.auth.exceptions.MalformedError``: a ValueError, not an IdentityError.

    The real class is ``MalformedError(GoogleAuthError, ValueError)``. What matters for the
    defect is precisely that it is NOT an ``IdentityError``, so nothing in the request path
    handled it and FastAPI answered a bare 500.
    """


@pytest.mark.parametrize(
    "raised",
    [
        _MalformedError("Can't parse segment header"),
        ValueError("Token has wrong audience x, expected y"),
        ValueError("Token expired, iat 1, exp 2, now 3"),
        ValueError("Could not verify token signature."),
        KeyError("kid"),
        RuntimeError("transport failure fetching the IAP key set"),
        OSError("offline: the key set could not be fetched"),
    ],
    ids=["malformed", "wrong-audience", "expired", "wrong-key", "keyerror", "transport", "oserror"],
)
def test_every_verifier_failure_becomes_an_identity_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, raised: Exception
) -> None:
    """The wrap, stated as a rule: nothing the caller can put in a header may reach the client
    as a 500. The original reason is kept on the exception (and so in the log and the chain)."""
    install_fake_google(monkeypatch, raised)
    with pytest.raises(IdentityError) as caught:
        adapter().resolve(context())
    assert "IAP assertion verification failed" in str(caught.value)
    assert caught.value.__cause__ is raised, "the original failure must stay on the chain"
    assert not isinstance(caught.value, EndUserAuthUnavailableError), (
        "a bad assertion is THIS caller's problem; the deployment can still authenticate others"
    )


def test_an_uninstalled_verifier_refuses_with_a_reason_rather_than_a_bare_500(
    no_cloud_sdk: None,
) -> None:
    """The second half of the wire proof: the bare 500 also happened with google-auth ABSENT.

    The lazy import is inside the ``try`` for exactly this. A deployment missing the managed
    extra can authenticate nobody, so it says so with a status and a message naming the fix,
    instead of raising ``ModuleNotFoundError`` per request out of a route.
    """
    with pytest.raises(IapVerifierUnavailableError) as caught:
        adapter().resolve(context())
    assert caught.value.http_status == 503
    assert "requirements-gcp.lock" in str(caught.value)
    assert isinstance(caught.value, EndUserAuthUnavailableError)


# --------------------------------------------------------------------------------------- #
# 4. The claims are checked after the signature, not trusted because it passed.
# --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        # The refusals come from `hex_service_kit.assertion.require_claims`, so the wording is
        # the commons' rather than this repository's. Two rows draw a distinction the others do
        # not: an issuer set to an empty string and an issuer that is absent are separated from a
        # wrong one, because `require_claims` treats a claim present but blank as missing rather
        # than as a value that fails to match.
        ({**GOOD_CLAIMS, "iss": "https://accounts.google.com"}, "does not accept"),
        ({**GOOD_CLAIMS, "iss": ""}, "missing required claim"),
        ({k: v for k, v in GOOD_CLAIMS.items() if k != "iss"}, "missing required claim"),
        ({**GOOD_CLAIMS, "sub": ""}, "missing required claim.*sub"),
        ({**GOOD_CLAIMS, "email": ""}, "missing required claim.*email"),
        ({k: v for k, v in GOOD_CLAIMS.items() if k != "email"}, "missing required claim.*email"),
    ],
    ids=["wrong-issuer", "blank-issuer", "no-issuer", "no-sub", "no-email", "email-absent"],
)
def test_a_verified_signature_does_not_excuse_the_claims(
    monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any], reason: str
) -> None:
    """``verify_token`` checks signature, audience and expiry. It does NOT check the issuer."""
    install_fake_google(monkeypatch, claims)
    with pytest.raises(IdentityError, match=reason):
        adapter().resolve(context())


def test_a_missing_hosted_domain_is_an_empty_tenant_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``hd`` is absent for consumer accounts; the tenant partition is empty, not invented."""
    install_fake_google(monkeypatch, {k: v for k, v in GOOD_CLAIMS.items() if k != "hd"})
    assert adapter().resolve(context()).tenant == ""


# --------------------------------------------------------------------------------------- #
# 5. On the wire: the API answers 401, never 500, for an assertion a caller wrote.
# --------------------------------------------------------------------------------------- #
#: A LAN peer. RFC 5737 documentation address: no real host, and obviously fictional.
LAN_PEER = "192.0.2.50"

#: The managed profile with its DATA ports rebound to the SDK-free adapters, so these tests
#: exercise the real gcp IDENTITY binding without needing Cloud Logging or a live console. This
#: is the documented rebinding path (``adapters:`` in the settings file), not a test-only hook.
_PKG = "contract_obligation_extraction"
_REBOUND_SETTINGS = "\n".join(
    [
        'audit_path: ":memory:"',
        "iap_audience: " + "${" + _AUDIENCE_ENV + ":-}",
        "adapters:",
        "  audit:",
        *[f"    {p}: {_PKG}.adapters.local.audit:LocalAuditAdapter" for p in ("local", "gcp")],
        f"    onprem: {_PKG}.adapters.onprem.audit:OnPremAuditAdapter",
        "  identity:",
        f"    local: {_PKG}.adapters.local.identity:LocalIdentityAdapter",
        f"    gcp: {_PKG}.adapters.gcp.identity:IapIdentityAdapter",
        f"    onprem: {_PKG}.adapters.onprem.identity:OnPremIdentityAdapter",
        "  review_router:",
        *[
            f"    {p}: {_PKG}.adapters.local.review_router:LocalReviewRouter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.review_router:OnPremReviewRouter",
        # Every port must bind every profile or `_bindings_from` refuses the whole file.
        "  tracer:",
        *[
            f"    {p}: {_PKG}.adapters.local.tracer:LocalNoopTracerAdapter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.tracer:OnPremTracerAdapter",
        "  evaluation:",
        *[
            f"    {p}: {_PKG}.adapters.local.evaluation:LocalOfflineEvalAdapter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.evaluation:OnPremEvalAdapter",
        # This vertical adds two ports (narration + contract extraction); the settings loader
        # requires every declared port to be bound, so a rebound file must carry them too.
        "  generation:",
        *[
            f"    {p}: {_PKG}.adapters.local.generation:LocalGenerationAdapter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.generation:OnPremGenerationAdapter",
        "  extraction:",
        *[
            f"    {p}: {_PKG}.adapters.local.extraction:LocalExtractionAdapter"
            for p in ("local", "gcp")
        ],
        f"    onprem: {_PKG}.adapters.onprem.extraction:OnPremExtractionAdapter",
    ]
)


def _managed_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, audience: str) -> Any:
    """Re-import the API module under the managed profile with the given audience.

    The postures are decided at import, so the module is rebuilt rather than patched, and the
    audience arrives through the settings file's ``${VAR}`` expansion exactly as a deployment
    supplies it. Three-state: UNSET takes the written default (here the empty string, which is
    the refusal), and SET-AND-EMPTY refuses at load instead. So "no audience configured" is
    expressed by UNSETTING the variable, never by blanking it; blanking it is its own error and
    is pinned by ``test_an_emptied_audience_variable_refuses_at_load``.
    """
    from tests.conftest import reimport

    path = tmp_path / "settings.yaml"
    path.write_text(_REBOUND_SETTINGS + "\n", encoding="utf-8")
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(_SETTINGS_ENV, str(path))
    if audience:
        monkeypatch.setenv(_AUDIENCE_ENV, audience)
    else:
        monkeypatch.delenv(_AUDIENCE_ENV, raising=False)
    return reimport(_API_MODULE)


def test_a_malformed_assertion_from_a_lan_peer_answers_401_and_never_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The refutation over the request path: the exact request that produced a bare 500.

    ``gcp`` is the one profile whose exposure guard stands down and whose process really does
    bind every interface, so this is a stranger reaching a real deployment.
    """
    install_fake_google(monkeypatch, _MalformedError("Can't parse segment header"))
    module = _managed_app(monkeypatch, tmp_path, AUDIENCE)
    with TestClient(module.app, client=(LAN_PEER, 50000)) as client:
        resp = client.post(
            "/v1/triage",
            json={"subject": "Acme (FICTIONAL)", "text": "urgent data breach"},
            headers={_IAP_ASSERTION_HEADER: "not-a-jwt"},
        )
    assert resp.status_code == 401, "a header a caller wrote may not become a 500"
    detail = resp.json()["detail"]
    assert detail == "authentication required"
    assert "audience" not in detail and "signature" not in detail, (
        "the specific reason belongs in the log and the exception chain, not in the answer to "
        "an unauthenticated caller who would be learning what to forge next"
    )


def test_an_unconfigured_audience_answers_503_with_the_variable_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The operator-facing half: this deployment can authenticate nobody, and says which knob."""
    module = _managed_app(monkeypatch, tmp_path, "")
    with TestClient(module.app, client=(LAN_PEER, 50000)) as client:
        resp = client.post(
            "/v1/triage",
            json={"subject": "Acme (FICTIONAL)", "text": "urgent data breach"},
            headers={_IAP_ASSERTION_HEADER: signed_assertion()},
        )
    assert resp.status_code == 503
    assert _AUDIENCE_ENV in resp.json()["detail"]


def test_an_emptied_audience_variable_refuses_at_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The other half of the split: UNSET is "not configured", EMPTIED is a configuration error.

    ``${CONTRACT_IAP_AUDIENCE:-}`` is expanded by the settings loader, and the loader refuses a
    variable an operator set to nothing rather than letting it resolve to the empty string that
    happens to mean "verify no audience". The refusal is loud, names the variable, and lands in
    the deploy rather than in traffic.
    """
    from hex_service_kit.netdefaults import ConfiguredEmptyError

    from contract_obligation_extraction.config import Settings

    path = tmp_path / "settings.yaml"
    path.write_text(_REBOUND_SETTINGS + "\n", encoding="utf-8")
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(_SETTINGS_ENV, str(path))
    monkeypatch.setenv(_AUDIENCE_ENV, "   ")
    with pytest.raises(ConfiguredEmptyError, match=_AUDIENCE_ENV):
        Settings.load(path)


def test_a_verified_assertion_is_served_so_the_refusals_above_mean_something(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The positive control. Without it, every assertion above is satisfied by a broken adapter.

    The escalation is ROUTED in the same request (rule R8) and the audit actor is the VERIFIED
    subject from the assertion, never anything in the body.
    """
    install_fake_google(monkeypatch, GOOD_CLAIMS)
    module = _managed_app(monkeypatch, tmp_path, AUDIENCE)
    with TestClient(module.app, client=(LAN_PEER, 50000)) as client:
        resp = client.post(
            "/v1/triage",
            json={"subject": "Acme (FICTIONAL)", "text": "urgent data breach"},
            headers={_IAP_ASSERTION_HEADER: signed_assertion()},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_human_review"] is True
    assert body["review_ref"], "an escalated result must be routed, not merely flagged"
