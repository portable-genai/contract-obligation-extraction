"""The negative matrix against a locally minted key: the REAL verifier, offline, no live GCP.

``test_iap_identity.py`` proves the adapter's own half with google-auth faked. A fake cannot
prove the half that matters most, because the fake is the thing under suspicion: that the
arguments the adapter passes actually cause google-auth to REJECT a wrong audience, an expired
token, a signature from the wrong key or a string that is not a JWT at all. Verified with
``audience=None`` (the defect) every one of those cells except the malformed one PASSES, and the
adapter would hand back a :class:`Principal` built from an attacker-chosen ``email``.

So this mints its own RSA key, signs its own assertions with it, serves its own public key from
an in-process transport, and runs the REAL ``google.oauth2.id_token.verify_token`` over the
result. No network, no project, no credential: the only thing faked is the HTTP fetch of the key
set, and the fake ASSERTS that the URL requested is IAP's published one, so the ``certs_url``
half of the fix is proved by the same harness.

    cell                     rejected by
    ------------------------ --------------------------------------------------
    wrong audience           google-auth, because audience= is now passed
    expired                  google-auth
    not yet issued           google-auth
    wrong signing key        google-auth, against IAP's key set
    malformed (not a JWT)    google-auth: MalformedError, a ValueError
    wrong issuer             this adapter, after a VALID signature
    absent header            this adapter, before the verifier exists
    empty header             this adapter, before the verifier exists
    unconfigured audience    this adapter, before anything is read
    a correct assertion      NOT rejected: the control that makes the rest mean something

WHY THIS MODULE MAY NOT SILENTLY SKIP. google-auth is in ``requirements-gcp.lock`` and not in
``requirements-dev.lock``, so the SDK-free ``make gate`` cannot import it. A module that just
skipped there would leave the fleet's most load-bearing adapter proved by nothing on the only
gate most people run. So the skip is CONDITIONAL ON AN ENVIRONMENT FLAG: where the runtime
lockfile is installed, the gate sets ``CONTRACT_REQUIRE_IAP_MATRIX=1`` and
a missing google-auth becomes a hard ERROR instead of a skip. The template's own render gate and
the shared hard-gate workflow's ``iap-verifier`` job both set it, and the render gate asserts the
module reported PASSED rather than skipped.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from hex_service_kit.identity import IdentityError, RequestContext

from contract_obligation_extraction.adapters.gcp.identity import (
    _IAP_ASSERTION_HEADER,
    _IAP_ISSUER,
    _IAP_KEYS_URL,
    IapAudienceUnconfiguredError,
    IapIdentityAdapter,
)
from contract_obligation_extraction.config import Settings

#: Set to "1" wherever google-auth IS installed, so absence becomes an error rather than a skip.
#: An exact-match read: unset, emptied and "0" all mean "not required", which fails closed for a
#: developer running the SDK-free gate and fails LOUD in the gate that installs the runtime lock.
_REQUIRE_ENV = "CONTRACT_REQUIRE_IAP_MATRIX"
_REQUIRED = os.environ.get(_REQUIRE_ENV) == "1"

try:  # noqa: SIM105 - the else branch is a skip, not a pass
    from google.auth import crypt as ga_crypt
    from google.auth import jwt as ga_jwt
    from google.auth.transport import requests as ga_requests
except ImportError as exc:  # pragma: no cover - exercised by whichever gate lacks the extra
    if _REQUIRED:
        raise RuntimeError(
            f"{_REQUIRE_ENV}=1 but google-auth is not importable, so the IAP negative matrix "
            "would have SKIPPED in a gate that exists to run it. Install the runtime lockfile "
            "(pip install -r requirements-gcp.lock) or stop setting the flag."
        ) from exc
    pytest.skip(
        f"google-auth is not installed (the SDK-free gate). Set {_REQUIRE_ENV}=1 where the "
        "runtime lockfile is installed to make this a hard failure instead.",
        allow_module_level=True,
    )

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError as exc:  # pragma: no cover - cryptography ships with the runtime lockfile
    if _REQUIRED:
        raise RuntimeError(
            f"{_REQUIRE_ENV}=1 but `cryptography` is not importable, so no key could be minted."
        ) from exc
    pytest.skip("cryptography is not installed", allow_module_level=True)


#: The IAP-protected resource this deployment verifies against. Obviously fictional.
AUDIENCE = "/projects/000000000000/global/backendServices/1111111111111111111"
#: A DIFFERENT protected resource: the audience an assertion minted for another service carries.
OTHER_AUDIENCE = "/projects/999999999999/global/backendServices/2222222222222222222"

SIGNING_KID = "iap-signing-key"
IMPOSTOR_KID = "impostor-key"


def _mint_key() -> tuple[Any, str]:
    """A fresh RSA keypair: the private key object and its public key as PEM.

    2048 bits, generated per session. Nothing here is a secret and nothing is committed: a key
    on disk in a template is a key in thirty-four repositories.
    """
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private, pem.decode("ascii")


def _signer(private_key: Any, kid: str) -> Any:
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return ga_crypt.RSASigner.from_string(pem, kid)


@pytest.fixture(scope="module")
def keys() -> dict[str, Any]:
    """IAP's signing key, plus an impostor key that IAP's key set does not contain."""
    iap_private, iap_public_pem = _mint_key()
    impostor_private, _ = _mint_key()
    return {
        "iap_signer": _signer(iap_private, SIGNING_KID),
        "impostor_signer": _signer(impostor_private, IMPOSTOR_KID),
        # The key set the fake transport serves: IAP's key only. An impostor-signed token
        # therefore has no key to verify against, exactly as it would in production.
        "certs": {SIGNING_KID: iap_public_pem},
    }


class _CertsResponse:
    """What ``google.auth.transport.Request.__call__`` returns: a status and a body."""

    def __init__(self, payload: dict[str, str]) -> None:
        self.status = 200
        self.data = json.dumps(payload).encode("utf-8")
        self.headers: dict[str, str] = {}


@pytest.fixture()
def fake_transport(monkeypatch: pytest.MonkeyPatch, keys: dict[str, Any]) -> list[str]:
    """Serve the minted key set in-process, and record every URL the verifier asked for.

    This is the ONLY thing faked. It also asserts the requested URL, so a regression that drops
    ``certs_url`` and falls back to google-auth's OAuth2 federated set fails HERE rather than
    silently verifying against keys IAP does not sign with.
    """
    requested: list[str] = []

    class _Request:
        def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> _CertsResponse:
            requested.append(url)
            assert url == _IAP_KEYS_URL, (
                f"the verifier fetched {url!r}, not IAP's key set. google-auth's default is the "
                "OAuth2 federated set, which signs tokens IAP never issued."
            )
            return _CertsResponse(keys["certs"])

    monkeypatch.setattr(ga_requests, "Request", _Request)
    return requested


def _assertion(
    keys: dict[str, Any],
    *,
    signer: str = "iap_signer",
    audience: str = AUDIENCE,
    issuer: str = _IAP_ISSUER,
    email: str = "analyst@bank.example",
    subject: str = "accounts.google.com:100000000000000000001",
    hosted_domain: str = "bank.example",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
    """Mint one IAP-shaped assertion. Every knob is a cell of the matrix."""
    now = issued_at or datetime.now(tz=UTC) - timedelta(seconds=30)
    exp = expires_at or (now + timedelta(minutes=10))
    payload: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "email": email,
        "hd": hosted_domain,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token: bytes = ga_jwt.encode(keys[signer], payload)
    return token.decode("ascii")


def _adapter(audience: str = AUDIENCE) -> IapIdentityAdapter:
    return IapIdentityAdapter(Settings(profile="gcp", iap_audience=audience))


def _resolve(assertion: str, *, audience: str = AUDIENCE) -> Any:
    ctx = RequestContext(headers={_IAP_ASSERTION_HEADER: assertion})
    return _adapter(audience).resolve(ctx)


# --------------------------------------------------------------------------------------- #
# The control. Without a cell that SUCCEEDS, every refusal below is satisfied by an adapter
# that refuses everything, which is not a service.
# --------------------------------------------------------------------------------------- #
def test_a_correctly_minted_assertion_verifies_and_yields_the_principal(
    keys: dict[str, Any], fake_transport: list[str]
) -> None:
    principal = _resolve(_assertion(keys))
    assert principal.subject == "analyst@bank.example"
    assert principal.tenant == "bank.example"
    assert principal.assurance == "iap"
    assert principal.source == "gcp-iap"
    assert fake_transport == [_IAP_KEYS_URL], "the verifier must fetch IAP's key set, once"


# --------------------------------------------------------------------------------------- #
# Rejected by google-auth, because the adapter now passes audience= and certs_url=.
# --------------------------------------------------------------------------------------- #
def test_an_assertion_for_another_service_is_rejected(
    keys: dict[str, Any], fake_transport: list[str]
) -> None:
    """THE defect. Signed by the right key, well formed, unexpired, and for somebody else.

    With ``audience=None`` this cell passes and ``analyst@bank.example`` becomes a verified
    principal on a service the token was never minted for.
    """
    with pytest.raises(IdentityError, match="verification failed"):
        _resolve(_assertion(keys, audience=OTHER_AUDIENCE))


def test_an_assertion_with_no_audience_claim_at_all_is_rejected(
    keys: dict[str, Any], fake_transport: list[str]
) -> None:
    with pytest.raises(IdentityError, match="verification failed"):
        _resolve(_assertion(keys, audience=""))


def test_an_expired_assertion_is_rejected(keys: dict[str, Any], fake_transport: list[str]) -> None:
    past = datetime.now(tz=UTC) - timedelta(hours=2)
    with pytest.raises(IdentityError, match="verification failed"):
        _resolve(_assertion(keys, issued_at=past, expires_at=past + timedelta(minutes=10)))


def test_an_assertion_issued_in_the_future_is_rejected(
    keys: dict[str, Any], fake_transport: list[str]
) -> None:
    ahead = datetime.now(tz=UTC) + timedelta(hours=2)
    with pytest.raises(IdentityError, match="verification failed"):
        _resolve(_assertion(keys, issued_at=ahead, expires_at=ahead + timedelta(minutes=10)))


def test_an_assertion_signed_by_the_wrong_key_is_rejected(
    keys: dict[str, Any], fake_transport: list[str]
) -> None:
    """Correct claims, correct audience, correct issuer, signed by a key IAP does not publish."""
    with pytest.raises(IdentityError, match="verification failed"):
        _resolve(_assertion(keys, signer="impostor_signer"))


@pytest.mark.parametrize(
    ("assertion", "reason"),
    [
        ("not-a-jwt", "not a compact JWS or JWE"),
        ("eyJhbGciOiJSUzI1NiJ9", "not a compact JWS or JWE"),
        ("a.b.c", "not base64url-encoded JSON"),
        ("...", "not a compact JWS or JWE"),
        (
            "eyJhbGciOiJub25lIn0.eyJlbWFpbCI6ImF0dGFja2VyQGV2aWwuZXhhbXBsZSJ9.",
            "alg 'none', which means it is UNSIGNED",
        ),
    ],
    ids=["garbage", "one-segment", "three-bad-segments", "dots", "alg-none"],
)
def test_a_malformed_assertion_is_a_refusal_and_never_an_escaping_exception(
    keys: dict[str, Any], fake_transport: list[str], assertion: str, reason: str
) -> None:
    """CRITICAL 2, at the source: ``MalformedError`` is a ``ValueError``, not an IdentityError.

    Unwrapped it escaped ``get_principal`` and FastAPI answered a bare 500. The ``alg: none``
    cell is here because an unsigned token is the classic way to skip verification entirely.

    Each cell asserts its OWN refusal reason rather than a shared "verification failed". The
    alg-none cell is why: a refusal that merely says "failed" cannot distinguish an unsigned
    token that was recognised as unsigned from one that was rejected for being unparseable, and
    those are different security properties.
    """
    with pytest.raises(IdentityError, match=re.escape(reason)):
        _resolve(assertion)


# --------------------------------------------------------------------------------------- #
# Rejected by the adapter, AFTER a valid signature: verify_token does not check the issuer.
# --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("issuer", "reason"),
    [
        ("https://accounts.google.com", "issued by a party this deployment does not accept"),
        (
            "https://securetoken.google.com/some-project",
            "issued by a party this deployment does not accept",
        ),
        ("", "missing required claim(s): iss"),
    ],
    ids=["oauth2-issuer", "firebase-issuer", "no-issuer"],
)
def test_a_validly_signed_assertion_from_the_wrong_issuer_is_rejected(
    keys: dict[str, Any], fake_transport: list[str], issuer: str, reason: str
) -> None:
    """Right key, right audience, unexpired. ``verify_token`` returns these claims happily.

    A NAMED wrong issuer and an ABSENT one are two refusals, not one: the first is a token from a
    real Google issuer this deployment does not federate with, the second names nobody at all.
    Matching both against the bare word "issuer" could not tell them apart.
    """
    with pytest.raises(IdentityError, match=re.escape(reason)):
        _resolve(_assertion(keys, issuer=issuer))


@pytest.mark.parametrize(
    ("email", "subject", "missing"),
    [("", "accounts.google.com:1", "email"), ("analyst@bank.example", "", "sub")],
    ids=["no-email", "no-sub"],
)
def test_a_validly_signed_assertion_with_no_identity_in_it_is_rejected(
    keys: dict[str, Any], fake_transport: list[str], email: str, subject: str, missing: str
) -> None:
    """The refusal must NAME the claim that was absent.

    "sub and email" was true of the old message and is true of neither refusal now; worse, it
    passed whichever claim was missing, so a verifier that had stopped checking ``sub`` entirely
    would still have satisfied the no-email cell.
    """
    with pytest.raises(IdentityError, match=re.escape(f"missing required claim(s): {missing}")):
        _resolve(_assertion(keys, email=email, subject=subject))


# --------------------------------------------------------------------------------------- #
# Rejected before the verifier is reached at all, so no network and no SDK can be involved.
# --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("headers", [{}, {_IAP_ASSERTION_HEADER: ""}, {_IAP_ASSERTION_HEADER: " "}])
def test_an_absent_or_empty_assertion_header_is_refused_untouched(
    fake_transport: list[str], headers: dict[str, str]
) -> None:
    with pytest.raises(IdentityError, match="missing IAP assertion header"):
        _adapter().resolve(RequestContext(headers=headers))
    assert fake_transport == [], "nothing should have been fetched"


@pytest.mark.parametrize("audience", ["", "   "])
def test_an_unconfigured_audience_refuses_even_a_perfect_assertion(
    keys: dict[str, Any], fake_transport: list[str], audience: str
) -> None:
    """The three-state read, cashed: there is no verify-without-an-audience path to fall into."""
    with pytest.raises(IapAudienceUnconfiguredError):
        _resolve(_assertion(keys), audience=audience)
    assert fake_transport == []


# --------------------------------------------------------------------------------------- #
# The mutant: prove this matrix would FAIL if the fix were reverted. A negative matrix nobody
# proved can go red is a green tick over an adapter that verifies nothing.
# --------------------------------------------------------------------------------------- #
def test_the_matrix_would_go_red_without_the_audience_argument(
    keys: dict[str, Any], fake_transport: list[str]
) -> None:
    """The original call, reproduced exactly: no ``audience=`` and no ``certs_url=``.

    ``certs_url`` is passed here only because the fake transport is the only key server in this
    process; what is being demonstrated is the audience. The token below was minted for a
    DIFFERENT protected resource, and the defective call accepts it and returns its claims.
    """
    from google.oauth2 import id_token

    foreign = _assertion(keys, audience=OTHER_AUDIENCE)
    claims = id_token.verify_token(foreign, ga_requests.Request(), certs_url=_IAP_KEYS_URL)
    assert claims["email"] == "analyst@bank.example", (
        "verify_token without audience= accepted an assertion minted for another service, which "
        "is the defect. If this ever stops being true, google-auth changed its default and the "
        "adapter's own audience check is what still holds."
    )
    # And the fixed adapter refuses the very same token.
    with pytest.raises(IdentityError):
        _resolve(foreign)
