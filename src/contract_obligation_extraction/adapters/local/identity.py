"""Local IdentityPort: seeded dev personas (no IdP/AD/LDAP), from the commons.

These personas are an UNAUTHENTICATED grant: the caller names one in a request header and gets
its groups and tenant. That is fine for an offline demo and is not fine for a deployment whose
profile variable simply went missing, so this adapter refuses to construct unless the local
profile was chosen DELIBERATELY. The profile must actually be ``local`` AND (when the settings
came from the environment) ``CONTRACT_PROFILE`` must have been set rather
than inherited from the offline default.

That second half is the whole point. An adapter that only checked ``profile == "local"`` would
still hand out an approver persona to the internet the moment the variable dropped out of a
deployment's environment, because the inherited value and the chosen value are the same string.
The :class:`ProfileChoice` in ``config.py`` keeps them apart; this is where the difference
is spent.
"""

from __future__ import annotations

from hex_service_kit.identity import (
    LocalPersonaIdentityAdapter,
    Principal,
    RequestContext,
)

from ...config import LOCAL_PROFILE, Settings
from ...ports.identity import CLIENT_ASSERTED, EndUserAuthUnavailableError


class LocalPersonaProfileError(EndUserAuthUnavailableError):
    """Raised when seeded dev personas would be served under a non-deliberate local profile.

    An :class:`~hex_service_kit.identity.IdentityError`, so the commons request dependency turns
    it into a 401 rather than a 500: the caller is not authenticated, and that is the honest
    answer whether the cause is a bad persona name or an unconfigured deployment. It is the
    "nobody can authenticate here" subclass, so the API answers with the message below rather
    than with a bare "authentication required" that points an operator at the wrong problem;
    the status stays 401, because a caller with no credential is exactly what this refuses.
    """


class LocalIdentityAdapter:
    """Resolve a Principal from a seeded dev persona (local profile only, CLIENT-ASSERTED).

    The declaration below is the load-bearing line for the exposure guard. These personas are
    chosen by a header the CALLER writes, so this adapter authenticates nobody and says so; the
    guard reads that and keeps the service on loopback. It says so whatever else is configured,
    because no other credential makes ``X-Dev-Persona`` a verified identity.
    """

    #: Seeded personas come from a header the client wrote. See ``ports/identity.py``.
    end_user_auth = CLIENT_ASSERTED

    def __init__(self, settings: Settings) -> None:
        if settings.profile != LOCAL_PROFILE:
            raise LocalPersonaProfileError(
                "seeded dev personas are local-profile only; "
                f"refusing to serve them under profile {settings.profile!r}"
            )
        if not settings.profile_explicit:
            raise LocalPersonaProfileError(
                "CONTRACT_PROFILE is not set, so the local profile was "
                "inherited rather than chosen; seeded dev personas grant their groups and "
                "tenant with no authentication and are refused. Set "
                "CONTRACT_PROFILE=local deliberately for a dev or demo "
                "run, or CONTRACT_PROFILE=gcp for a real deployment."
            )
        self._settings = settings
        self._inner = LocalPersonaIdentityAdapter()

    def resolve(self, ctx: RequestContext) -> Principal:
        return self._inner.resolve(ctx)

    def personas(self) -> tuple[dict[str, str], ...]:
        return self._inner.personas()
