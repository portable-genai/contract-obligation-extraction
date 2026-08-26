"""The CLAIM half of the IAP adapter: one reviewed decision, not a local copy of one.

Signature verification stays in the adapter, because it needs a cloud SDK and
``hex_service_kit``'s core is pure standard library. Everything AFTER the signature -- which
string is the subject, which partition is the tenant, which entitlement principals the caller
holds, what assurance the audit record carries -- is a single authorization decision that was
replicated in fifty adapters, and it is now
:func:`hex_service_kit.federation.principal_from_iap_claims`.

**What was observed failing first, before the adapter changed.** Every test below was run
against the adapter exactly as it shipped:

* ``test_the_claim_half_is_the_commons_decision_and_not_a_local_copy`` failed on the ``acr``
  row and on the mixed-case ``hd`` row. The shipped tail hardcoded ``assurance="iap"`` and
  ignored an ``acr`` the commons prefers, and it passed the ``hd`` claim through with only
  ``.strip()`` where the commons lower-cases it. Both are recorded as findings in
  ``docs/practices-audit.md``: they are behaviour changes, not formatting.
* ``test_the_hosted_domain_passthrough_is_an_opt_in_this_deployment_made`` failed with
  ``AttributeError``: there was no policy object to read, which is exactly the state in which
  a load-bearing tenant can be emptied by a default nobody wrote down.
* ``test_a_claim_set_from_another_issuer_cannot_become_a_principal`` failed by RETURNING a
  principal. With the claim-set precheck removed, the hand-rolled tail read ``claims["email"]``
  and built a verified identity out of a token issued by somebody else. The commons refuses it
  a second time, which is what makes the precheck a defence in depth rather than the only
  defence.

The knobs were also flipped deliberately after the change: setting
``include_subject_principal=True`` turns
``test_this_family_withholds_the_verified_subject_its_own_principal`` red, and clearing
``tenant_from_hosted_domain`` turns the passthrough test and the ``hd`` rows of the
comparison red. A guard that cannot be made to fail is not a guard.
"""

from __future__ import annotations

import base64
import json as _json
from typing import Any

import pytest
from hex_service_kit.federation import (
    IAP_ASSERTION_HEADER,
    IAP_ISSUER,
    FederationPolicy,
    principal_from_iap_claims,
)
from hex_service_kit.identity import IdentityError, RequestContext

from contract_obligation_extraction.adapters.gcp.identity import (
    _FEDERATION_POLICY,
    IapIdentityAdapter,
)

_AUDIENCE = "/projects/1234567890/global/backendServices/42"
_EMAIL = "avery.stone@example-bank.test"
_SUB = "accounts.google.com:100000000000000000001"


def _token() -> str:
    """A structurally real compact JWS. Only the header is read, and nothing is signed."""
    header = (
        base64.urlsafe_b64encode(_json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    return f"{header}.{base64.urlsafe_b64encode(b'{}').decode().rstrip('=')}.c2ln"


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": IAP_ISSUER,
        "aud": _AUDIENCE,
        "sub": _SUB,
        "email": _EMAIL,
        "hd": "example-bank.test",
        "exp": 4102444800,
    }
    claims.update(overrides)
    return {name: value for name, value in claims.items() if value is not None}


def _adapter(audience: str = _AUDIENCE) -> IapIdentityAdapter:
    """The adapter with only the deployment configuration ``resolve`` reads.

    Built without ``Settings`` so this module depends on the identity binding and on nothing
    else in the container. The same idiom the refusal-split suite uses.
    """
    adapter = object.__new__(IapIdentityAdapter)
    adapter._settings = None
    adapter._audience = audience
    adapter._audience_configured_empty = False
    return adapter


def _resolve(claims: dict[str, Any], adapter: IapIdentityAdapter | None = None) -> Any:
    """Run the shipped adapter's claim half over ``claims``, with the cryptography stubbed.

    The signature check is the half that stays in the adapter and needs google-auth, which the
    offline gate does not install. Stubbing ``_verify`` is what makes the half under test
    reachable without a network, a credential or a cloud SDK; it is not a way of skipping a
    check, because every refusal the verifier owns is exercised by the crypto suite instead.
    """
    adapter = adapter or _adapter()
    object.__setattr__(adapter, "_verify", lambda assertion: dict(claims))
    return adapter.resolve(RequestContext(headers={IAP_ASSERTION_HEADER: _token()}))


def _fields(principal: Any) -> tuple[Any, ...]:
    """Compare by VALUE, not by identity of the class.

    Some repositories in this family still declare their own look-alike ``Principal`` instead
    of re-exporting the commons one, so ``==`` between the two answers would be False for a
    reason that has nothing to do with the decision under test.
    """
    return (
        principal.subject,
        principal.principals,
        principal.tenant,
        principal.assurance,
        principal.source,
    )


# --------------------------------------------------------------------------------------- #
# The comparison. Executed against the commons, never read off it.
# --------------------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name,claims",
    [
        ("workspace user", _claims()),
        ("no hosted domain", _claims(hd=None, email="someone@personal.test")),
        ("service account", _claims(hd=None, email="runner@demo.iam.gserviceaccount.com")),
        ("assertion carrying acr", _claims(acr="urn:mace:incommon:iap:silver")),
        ("hosted domain in mixed case", _claims(hd="Example-Bank.TEST")),
    ],
)
def test_the_claim_half_is_the_commons_decision_and_not_a_local_copy(
    name: str, claims: dict[str, Any]
) -> None:
    """Every field of the resolved principal is what the commons decides, for every shape.

    A copy that agrees today is a copy that can drift tomorrow with nothing to notice, which
    is the whole reason the decision moved. Comparing the ANSWERS rather than the source is
    what turns that from a claim into a check.
    """
    assert _fields(_resolve(claims)) == _fields(
        principal_from_iap_claims(
            claims,
            _FEDERATION_POLICY,
            source="gcp-iap",
            include_subject_principal=False,
        )
    ), name


# --------------------------------------------------------------------------------------- #
# The one authorization decision the two adapter families make differently.
# --------------------------------------------------------------------------------------- #
def test_this_family_withholds_the_verified_subject_its_own_principal() -> None:
    """This family withholds ``user:<subject>`` and leaves the tuple to the group map.

    The other adapter family grants it, and both are deliberate. Adopting the commons
    without saying which one this repository is would have silently granted every
    verified user an entitlement principal nothing here reviews.

    ``include_subject_principal`` is a parameter precisely because the two families disagree
    on purpose. Flipping it here is a one-character edit, so it is asserted directly rather
    than inferred from a passing suite.
    """
    assert _resolve(_claims()).principals == ()


# --------------------------------------------------------------------------------------- #
# The tenancy boundary. A domain nobody asserted is not an organisation.
# --------------------------------------------------------------------------------------- #
def test_an_assertion_with_no_hosted_domain_resolves_to_no_tenant() -> None:
    """The mail domain is DERIVED and asserts nothing, so it must never become a tenant.

    A personal account the edge admits, or an external federated identity, carries no ``hd``
    at all. Reading its address instead would make anyone able to receive mail at a domain
    they control a tenant of that domain, silently, at a tenancy boundary. The commons shipped
    exactly that defect once and removed it; this is the repository-side guard that it stays
    removed.
    """
    principal = _resolve(_claims(hd=None, email="someone@personal.test"))
    assert principal.tenant == ""


def test_the_hosted_domain_passthrough_is_an_opt_in_this_deployment_made() -> None:
    """The policy is load-bearing, and the test proves it by turning it off.

    With passthrough cleared, the SAME verified assertion resolves to no tenant. That is
    fail-closed and it is closed for every user, which is why the choice is written down as a
    reviewed policy object rather than left to a default. No domain is mapped, because this
    deployment has no reviewed domain map: an unmapped domain must therefore get its tenant
    from the opt-in or from nothing.
    """
    assert _FEDERATION_POLICY.tenant_from_hosted_domain is True
    assert dict(_FEDERATION_POLICY.domain_tenants) == {}
    assert dict(_FEDERATION_POLICY.domain_groups) == {}

    without = FederationPolicy()
    assert without.tenant_for("example-bank.test", email_domain="example-bank.test") == ""
    assert _FEDERATION_POLICY.tenant_for("example-bank.test") == "example-bank.test"

    # The tenant a verified user actually receives, which is the half an attribute assertion
    # cannot see. The comparison test above evaluates BOTH sides under this same policy, so it
    # agrees whichever policy is configured; only a resolved value can catch an emptied tenant,
    # and an emptied tenant is precisely the failure that fails closed for everybody at once.
    assert _resolve(_claims()).tenant == "example-bank.test"


# --------------------------------------------------------------------------------------- #
# The attacker's side: a verified signature is not a verified issuer.
# --------------------------------------------------------------------------------------- #
def test_a_claim_set_from_another_issuer_cannot_become_a_principal() -> None:
    """Defence in depth, asserted with the first defence deliberately removed.

    ``_refuse_unpinned_claims`` already refuses a foreign issuer. This test takes it away, so
    that what is being measured is the claim half itself: a token that satisfied a signature
    check and named somebody else as its issuer must produce NO principal, rather than a
    verified identity built out of its ``email``.
    """
    adapter = _adapter()
    object.__setattr__(adapter, "_refuse_unpinned_claims", lambda claims: None)
    with pytest.raises(IdentityError):
        _resolve(_claims(iss="https://accounts.google.com"), adapter)


def test_a_verified_assertion_that_names_nobody_is_refused() -> None:
    """An empty subject is not an anonymous caller; it is an assertion with no actor to audit."""
    adapter = _adapter()
    object.__setattr__(adapter, "_refuse_unpinned_claims", lambda claims: None)
    with pytest.raises(IdentityError):
        _resolve(_claims(sub="   "), adapter)
