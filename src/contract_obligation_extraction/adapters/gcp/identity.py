"""GCP IdentityPort: verify the IAP-injected signed assertion (SDK imports stay lazy).

This adapter is the linchpin of the serving posture. It is the ONE shipped adapter that declares
``VERIFIED`` (see ``ports/identity.py``), and that declaration is the
single flag the exposure guard reads before it stands down and lets the process bind every
interface (``api/app.py``). So the verification has to be real, and every way it can fail has to
come out as a refusal rather than as a crash. Three things make that true, and all three were
once absent:

**1. The audience is verified, and it is CONFIGURATION.** ``id_token.verify_token`` documents
``audience=None`` as "the audience is not verified". Called without one, it accepts ANY
Google-signed OIDC ID token, from any project and any application, and hands back its claims, so
a token minted for an unrelated service becomes a verified :class:`Principal` here. The audience
is per-deployment (the IAP-protected resource), so it is read from settings, never written as a
literal, and it is three-state: UNSET and SET-AND-EMPTY both arrive as ``""`` and both REFUSE.
Verifying-without-an-audience is not a fallback this adapter has.

**2. The keys are IAP's keys.** ``certs_url`` defaults to the OAuth2 federated certificate set,
which is not the set IAP signs with. Pinning :data:`_IAP_KEYS_URL` means a token signed by any
other Google key set fails the signature check instead of reaching the claim reader.

**3. A crash is not a refusal.** ``google.auth.exceptions.MalformedError`` is a ``ValueError``
and a ``GoogleAuthError``; it is NOT an :class:`~hex_service_kit.identity.IdentityError`. Left
unwrapped it escaped ``get_principal`` entirely and FastAPI answered a bare 500 with no body, so
``X-Goog-IAP-JWT-Assertion: not-a-jwt`` from an uncredentialed LAN peer got a stack-trace-shaped
nothing instead of a 401. The verifier call is wrapped, and so is the lazy import: a deployment
with the ``[gcp]`` extra missing cannot verify anybody, and it says that with a status and a
reason rather than crashing per request.

The refusals are split by who can act on them, which is the same split ``ports/identity.py``
draws. A malformed, expired, wrong-audience, wrong-issuer or wrong-key assertion is THIS
caller's problem: a plain :class:`~hex_service_kit.identity.IdentityError`, answered 401, with
the specific reason kept in the exception (and so in the log and the exception chain) rather
than handed to an unauthenticated caller who would be learning what to forge next. An
unconfigured audience or an uninstalled verifier is the DEPLOYMENT's problem: nobody can
authenticate here and no credential would have helped, so those raise
``EndUserAuthUnavailableError`` subclasses (``ports/identity.py``)
that carry their own status and their own message to the operator.

The Google SDK imports stay inside the method so the SDK-free ``local`` and ``onprem`` profiles
import this module with no cloud SDK installed.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit.assertion import require_claims, require_pinned_algorithm
from hex_service_kit.federation import IAP_ASSERTION_HEADER, IAP_ISSUER, IAP_KEYS_URL
from hex_service_kit.identity import IdentityError, Principal, RequestContext

from ...config import Settings
from ...ports.identity import VERIFIED, EndUserAuthUnavailableError

# The three transport facts are REBOUND from the kit, not re-declared here. They are the same
# three strings in every repository that verifies an IAP assertion, and while each kept its own
# copy the population could drift with nothing to notice: a repo that edited one of them alone
# would still gate green, because a literal always agrees with itself. Rebinding makes a
# divergence between this adapter and the reviewed set impossible rather than merely unlikely.
_IAP_ASSERTION_HEADER = IAP_ASSERTION_HEADER

#: The key set IAP signs its assertions with. NOT google-auth's default, which is the OAuth2
#: federated set: pass no ``certs_url`` and a token signed by a different Google key set verifies.
_IAP_KEYS_URL = IAP_KEYS_URL

#: The issuer every IAP assertion carries. ``verify_token`` does not check the issuer at all
#: (``verify_oauth2_token`` is the wrapper that does), so this adapter checks it itself.
_IAP_ISSUER = IAP_ISSUER

#: The claims this deployment requires before it reads any of them. Stated as a set rather than
#: checked one field at a time, so adding a requirement is one edit and a claim that is present
#: but EMPTY counts as missing, which the previous per-field readers could not express.
_REQUIRED_CLAIMS = ("iss", "sub", "email", "exp")

#: Named for the refusal messages. The value is read through ``config/settings.yaml``, whose
#: ``${VAR}`` expansion is the three-state read; nothing here touches ``os.environ``.
_AUDIENCE_ENV = "CONTRACT_IAP_AUDIENCE"

_UNCONFIGURED_AUDIENCE = (
    f"{_AUDIENCE_ENV} is not configured, so no IAP assertion can be verified and this "
    "deployment can authenticate nobody. Verifying WITHOUT an audience is not a fallback: "
    "google-auth documents audience=None as 'the audience is not verified', which would accept "
    "any Google-signed OIDC token from any project or application. Set it to the IAP-protected "
    "resource, /projects/<NUM>/global/backendServices/<ID>."
)

_VERIFIER_UNAVAILABLE = (
    "the IAP assertion verifier is not installed, so this deployment can authenticate nobody. "
    "Install the managed extra (pip install -r requirements-gcp.lock, or '.[gcp]') so "
    "google-auth is importable, or run a profile whose identity adapter needs no cloud SDK."
)


class IapAudienceUnconfiguredError(EndUserAuthUnavailableError):
    """No audience is configured, so nobody can be authenticated on this deployment.

    503 rather than 401: a caller who presented a perfectly good IAP assertion would be refused
    exactly the same way, so inviting them to authenticate would be a lie. The message names the
    variable, because the fix is in the deployment and not in the request.
    """

    http_status = 503


class IapVerifierUnavailableError(EndUserAuthUnavailableError):
    """google-auth is not importable, so no assertion can be checked at all.

    Also 503, and for the same reason. This exists so that the missing-SDK case is a refusal
    with a reason instead of the bare 500 an unwrapped ``ModuleNotFoundError`` produced: an
    uncredentialed caller got an empty error page and the operator got nothing to read.
    """

    http_status = 503


class IapIdentityAdapter:
    """Resolve a verified Principal from the Identity-Aware-Proxy assertion header.

    This is the one adapter in the shipped set that declares :data:`VERIFIED`, and
    :meth:`resolve` is where it earns it: the assertion's SIGNATURE (against IAP's own key set),
    AUDIENCE (against the configured protected resource), EXPIRY and ISSUER are all checked
    before a single claim is read, so a caller cannot name itself by writing a header. That
    declaration is what lets the exposure guard stand down; see ``ports/identity.py``.
    """

    #: A signed assertion, verified here. See ``ports/identity.py``.
    end_user_auth = VERIFIED

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Stripped, so a variable a deployment template rendered blank is UNSET rather than an
        # audience: a whitespace-only value is truthy, and handing it to the verifier as the
        # expected audience would refuse every real token while looking configured.
        self._audience = settings.iap_audience.strip()

    def resolve(self, ctx: RequestContext) -> Principal:
        # The configuration check comes FIRST, before the assertion header is even read. An
        # unconfigured audience is a deployment that can authenticate nobody, and refusing on
        # that alone means the refusal never depends on the Google SDK being importable, on the
        # network, or on what the caller happened to present.
        if not self._audience:
            raise IapAudienceUnconfiguredError(_UNCONFIGURED_AUDIENCE)
        assertion = ctx.header(_IAP_ASSERTION_HEADER).strip()
        if not assertion:
            raise IdentityError("missing IAP assertion header; request did not pass through IAP")
        # The ALGORITHM is judged before the verifier is handed the token, with no cryptography
        # and no cloud SDK, so this refusal is exercised by the offline gate rather than living
        # inside a library the gate never installs. `alg: none` is an unsigned assertion, and the
        # symmetric HS* family would let the public key everybody already has sign a token.
        self._refuse_unpinned_algorithm(assertion)
        claims = self._verify(assertion)
        # verify_token checks signature, audience and expiry. It does NOT check the issuer, and
        # it does not require that the assertion identify anybody, so the issuer and the claim
        # SET are both stated here rather than inherited.
        self._refuse_unpinned_claims(claims)
        email = str(claims["email"]).strip()
        return Principal(
            subject=email,
            tenant=str(claims.get("hd") or "").strip(),
            assurance="iap",
            source="gcp-iap",
        )

    def _refuse_unpinned_algorithm(self, assertion: str) -> None:
        """Refuse an assertion signed with an algorithm this deployment does not accept.

        The kit's refusal is already an ``IdentityError``, which this module maps to a 401, so
        it is allowed through unchanged; the wrapper exists so the call site reads as a policy
        decision rather than as a library call.
        """
        require_pinned_algorithm(assertion)

    def _refuse_unpinned_claims(self, claims: dict[str, Any]) -> None:
        """Refuse a verified assertion missing a required claim or naming the wrong party."""
        require_claims(
            claims,
            issuer=_IAP_ISSUER,
            audience=self._audience,
            required=_REQUIRED_CLAIMS,
        )

    def _verify(self, assertion: str) -> dict[str, Any]:
        """Hand the assertion to google-auth with the audience and the key set pinned.

        Every failure mode of the managed verifier crosses this boundary as an
        :class:`~hex_service_kit.identity.IdentityError`. That includes the ones that are not
        ``IdentityError`` subclasses and never were: ``MalformedError`` (a ``ValueError``),
        ``ValueError`` for a wrong audience, an expired token or an unverifiable signature, and
        any transport failure fetching the key set. A caller may not turn a header into a 500.
        """
        try:
            # Lazy import: absent offline and in CI (``google.*`` is declared unstubbed in
            # pyproject, so mypy says the same thing whether or not it happens to be installed).
            # Inside the try because an uninstalled verifier must refuse with a reason, not crash.
            from google.auth.transport import requests as ga_requests
            from google.oauth2 import id_token
        except ImportError as exc:
            raise IapVerifierUnavailableError(_VERIFIER_UNAVAILABLE) from exc
        try:
            claims: dict[str, Any] = dict(
                id_token.verify_token(
                    assertion,
                    ga_requests.Request(),
                    audience=self._audience,
                    certs_url=_IAP_KEYS_URL,
                )
            )
        except Exception as exc:  # noqa: BLE001 - every verifier failure becomes a refusal
            raise IdentityError(f"IAP assertion verification failed: {exc}") from exc
        return claims
