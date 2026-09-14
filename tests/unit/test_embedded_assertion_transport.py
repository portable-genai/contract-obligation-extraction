"""The header an assertion arrives under once this service is EMBEDDED, and what it costs.

**The contradiction this module exists to resolve.** ``test_iap_identity.py`` already asserts
that a verified assertion resolves to a principal, and it passes. A sibling application asserting
the same thing still answered ``401`` to every authenticated caller the day it was deployed
behind the portal. Both are true, and the reason is that every test in that file hands the
adapter its assertion like this:

    RequestContext(headers={_IAP_ASSERTION_HEADER: signed_assertion()})

``_IAP_ASSERTION_HEADER`` is ``x-goog-iap-jwt-assertion``, the one header production never
delivers to an embedded application. ``x-goog-*`` is Google's reserved namespace and the
serverless frontend REMOVES that whole namespace from a request entering a service, so an
embedding host behind IAP cannot forward what its own edge handed it: the host sets the reserved
name, the frontend drops it, and the service refuses "request did not pass through IAP" about a
request that passed through IAP one hop earlier. The broker sends the same value as
``x-portal-iap-assertion`` as well, precisely because that name is NOT reserved.

So the suite next door models the CLAIMS faithfully and models the TRANSPORT wrongly. It is right
about what it asserts and silent about the half that fails, which is the shape of a test that
builds its own request: the fixture chooses the header, so it can only ever choose the one the
author had in mind.

**What was observed failing first.** On 2026-09-12 two applications were deployed on the same
day and both refused a service-account caller through the portal's IAP edge, while a third,
deployed a week earlier through the same hosts with the same audience, answered it. The kit
release, the audience, the host and the proxy were all excluded by execution. The difference was
one line, and it is the line these tests pin. The refusal was also invisible to a browser
walkthrough, because a console's first calls need no identity at all.

Nothing here needs a cloud SDK, a project or a network: the cryptography is either stubbed or
blocked outright, and every check this adapter owns before and after the verifier still runs.
"""

from __future__ import annotations

import base64
import json as _json
from typing import Any

import pytest
from hex_service_kit import federation as kit_federation
from hex_service_kit.identity import IdentityError, RequestContext

from contract_obligation_extraction.adapters.gcp.identity import (
    _IAP_ASSERTION_HEADER,
    _IAP_ISSUER,
    _PORTAL_ASSERTION_HEADER,
    IapIdentityAdapter,
    IapVerifierUnavailableError,
)
from contract_obligation_extraction.config import Settings

#: A configured audience: the IAP-protected resource, obviously fictional.
AUDIENCE = "/projects/000000000000/global/backendServices/1111111111111111111"

#: The claim set a real IAP assertion carries once verified, for a human in a hosted domain.
GOOD_CLAIMS: dict[str, Any] = {
    "iss": _IAP_ISSUER,
    "sub": "accounts.google.com:100000000000000000001",
    "email": "analyst@bank.example",
    "hd": "bank.example",
    "exp": 1_900_000_000,
}


def signed_assertion() -> str:
    """A structurally real compact JWS, because the algorithm pin reads the JOSE header.

    Nothing here is signed; only the header is ever parsed. A fixture that is not a JWS would be
    refused by ``require_pinned_algorithm`` before the transport question was reached, and would
    prove nothing about a token that can actually exist.
    """
    header = (
        base64.urlsafe_b64encode(_json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = base64.urlsafe_b64encode(b'{"sub":"1"}').decode().rstrip("=")
    return f"{header}.{payload}.c2ln"


def adapter(audience: str = AUDIENCE) -> IapIdentityAdapter:
    return IapIdentityAdapter(Settings(profile="gcp", iap_audience=audience))


def resolving_adapter(
    monkeypatch: pytest.MonkeyPatch,
    claims: dict[str, Any] | None = None,
    seen: list[str] | None = None,
) -> IapIdentityAdapter:
    """The shipped adapter with ONLY the cryptography stubbed.

    Stubbing ``_verify`` is what makes the half under test reachable with no network, no
    credential and no cloud SDK. It skips no check the adapter owns: the algorithm pin, the
    required claims, the issuer and the audience are all still evaluated, and every refusal the
    verifier itself owns is exercised by ``test_iap_crypto_matrix.py`` against a real one.
    """
    built = adapter()

    def _verify(assertion: str) -> dict[str, Any]:
        if seen is not None:
            seen.append(assertion)
        resolved = dict(claims or GOOD_CLAIMS)
        resolved.setdefault("aud", AUDIENCE)
        return resolved

    monkeypatch.setattr(built, "_verify", _verify)
    return built


# --------------------------------------------------------------------------------------- #
# The transport. One assertion, two names, and only one of them survives the hop.
# --------------------------------------------------------------------------------------- #
def test_the_forwarded_header_name_is_the_commons_value_and_is_not_reserved() -> None:
    """Rebound from the kit, never re-declared, and OUTSIDE the stripped namespace.

    Putting the fallback back inside ``x-goog-*`` would reintroduce the exact defect it fixes,
    silently, because the frontend strips the whole namespace rather than one name.
    """
    assert _PORTAL_ASSERTION_HEADER == kit_federation.PORTAL_ASSERTION_HEADER
    assert _PORTAL_ASSERTION_HEADER == "x-portal-iap-assertion"
    assert not _PORTAL_ASSERTION_HEADER.startswith("x-goog-")
    assert _IAP_ASSERTION_HEADER.startswith("x-goog-"), "the reserved name is the stripped one"


def test_a_verified_caller_resolves_when_an_embedding_host_forwarded_the_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline reproduction of the live 401, and the resolution of the contradiction.

    Identical claims, identical policy and an identical assertion to the suite next door. The
    ONLY difference is the header name, and the header name was the whole defect: under the
    forwarded name, which is the only one an embedded application ever sees, the adapter as it
    shipped refused with "missing IAP assertion header" and no claim was ever read.
    """
    principal = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_PORTAL_ASSERTION_HEADER: signed_assertion()})
    )

    assert principal.subject == "analyst@bank.example"
    assert principal.tenant == "bank.example"
    assert principal.source == "gcp-iap"


def test_both_names_yield_the_same_principal_from_the_same_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback is TRANSPORT, not a second trust path with its own outcome.

    If the two names could ever produce different identities, the header would be vouching for
    something, and a caller could choose what it vouched for.
    """
    token = signed_assertion()
    edge = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_IAP_ASSERTION_HEADER: token})
    )
    forwarded = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_PORTAL_ASSERTION_HEADER: token})
    )
    assert edge == forwarded


@pytest.mark.parametrize(
    "header",
    [kit_federation.IAP_ASSERTION_HEADER, kit_federation.PORTAL_ASSERTION_HEADER],
    ids=["edge-injected", "host-forwarded"],
)
def test_neither_name_buys_a_bypass_of_the_verifier(header: str, no_cloud_sdk: None) -> None:
    """Both names reach the VERIFIER, and here the verifier is unimportable.

    ``_verify`` is deliberately NOT stubbed and the SDK is blocked, so the only acceptable
    outcome is the deployment-shaped refusal. A returned identity would mean the header bought a
    bypass; a "missing IAP assertion header" would mean the header was ignored.
    """
    with pytest.raises(IapVerifierUnavailableError) as caught:
        result = adapter().resolve(RequestContext(headers={header: signed_assertion()}))
        raise AssertionError(f"an unverified assertion produced an identity: {result!r}")
    assert "missing IAP assertion header" not in str(caught.value)


def test_the_edge_injected_name_still_wins_when_both_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Precedence is about diagnosis, not trust: the direct edge's assertion needs no forwarding.

    Both are verified identically, so nothing turns on the order; pinning it keeps the common
    path the simple one when a service is reached both directly and through a host.
    """
    edge = signed_assertion()
    seen: list[str] = []
    resolving_adapter(monkeypatch, seen=seen).resolve(
        RequestContext(
            headers={
                _IAP_ASSERTION_HEADER: edge,
                _PORTAL_ASSERTION_HEADER: "forwarded-and-different",
            }
        )
    )
    assert seen == [edge]


def test_the_header_is_found_whatever_case_the_hop_wrote_it_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP header names are case-insensitive, and the selection is a dictionary lookup.

    An identity that goes missing because a hop capitalised the name is the same silent refusal
    as an identity that goes missing because the name was reserved.
    """
    principal = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_PORTAL_ASSERTION_HEADER.upper(): signed_assertion()})
    )
    assert principal.subject == "analyst@bank.example"


# --------------------------------------------------------------------------------------- #
# The fix must not swallow the ordinary case.
# --------------------------------------------------------------------------------------- #
def test_neither_name_present_is_still_a_missing_assertion(no_cloud_sdk: None) -> None:
    """And the refusal must NAME both headers it examined.

    An operator who reads only "missing IAP assertion header" goes to the load balancer. The one
    who reads which two names were looked for goes to the hop that dropped one of them.
    """
    with pytest.raises(IdentityError) as caught:
        adapter().resolve(RequestContext(headers={}))
    message = str(caught.value)
    assert "missing IAP assertion header" in message
    assert kit_federation.IAP_ASSERTION_HEADER in message
    assert kit_federation.PORTAL_ASSERTION_HEADER in message


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
@pytest.mark.parametrize(
    "header",
    [kit_federation.IAP_ASSERTION_HEADER, kit_federation.PORTAL_ASSERTION_HEADER],
    ids=["edge-injected", "host-forwarded"],
)
def test_a_whitespace_only_header_is_an_absent_one_under_either_name(
    header: str, blank: str, no_cloud_sdk: None
) -> None:
    """A blank value is TRUTHY, so unstripped it would be refused as a malformed token instead.

    That refusal reports the wrong fault: a proxy that rendered the variable empty is a missing
    assertion, not a caller presenting a broken one.
    """
    with pytest.raises(IdentityError, match="missing IAP assertion header"):
        adapter().resolve(RequestContext(headers={header: blank}))
