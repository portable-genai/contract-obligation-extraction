"""What an identity adapter DECLARES about the end-user authentication it can provide.

The exposure guard on the app object has one question to answer before it can decide anything:
are this service's END-USER routes authenticated? Nothing else in the configuration answers it.

* The PROFILE names an adapter family, not an authentication scheme. A deliberate ``local`` and
  an inherited one bind the same seeded personas, and a client's own IdP adapter can be bound
  under ``onprem`` without the profile string changing at all.
* The SERVICE-TO-SERVICE secret authenticates a calling SERVICE. It authenticates no end user,
  so its presence is not evidence that ``/v1/triage`` is protected. Deriving the guard from it
  is how setting a credential came to SWITCH THE GUARD OFF for the routes it was protecting.

The adapter bound to the identity port is the only thing that knows, so it says so here, and
the guard reads the answer from the binding rather than inferring it from something else.

Three answers, and the difference between the first two is the whole point:

* :data:`VERIFIED` - the adapter resolves a principal from something it VERIFIES server side (a
  signed assertion whose signature, issuer and expiry it checks). A caller cannot name itself,
  so end-user routes ARE authenticated.
* :data:`CLIENT_ASSERTED` - the adapter resolves a principal from something the CLIENT wrote
  (the seeded ``X-Dev-Persona`` picker). A caller chooses who it is, so end-user routes are NOT
  authenticated, however many other credentials the deployment has configured.
* :data:`UNIMPLEMENTED` - the adapter resolves nobody at all: a portability placeholder waiting
  for the client's own IdP. Nobody can be authenticated, so nothing is.

An adapter that declares NOTHING is read as :data:`CLIENT_ASSERTED`, never :data:`VERIFIED`.
Silence is not a claim to verify anything, and a guard that reads silence as "authenticated"
switches itself off for every adapter somebody forgot to annotate, which is the fail-open shape
this module exists to remove.
"""

from __future__ import annotations

from hex_service_kit.identity import IdentityError

#: The adapter verifies a server-side assertion; the client cannot assert who it is.
VERIFIED = "verified"
#: The adapter believes a header the client wrote. Useful offline, not authentication.
CLIENT_ASSERTED = "client-asserted"
#: The adapter resolves nobody: a placeholder for an identity provider not yet bound.
UNIMPLEMENTED = "unimplemented"

#: Every declaration this service understands. Anything else is read as :data:`CLIENT_ASSERTED`.
END_USER_AUTH_KINDS: frozenset[str] = frozenset({VERIFIED, CLIENT_ASSERTED, UNIMPLEMENTED})

#: The class attribute an identity adapter sets to one of the values above. A CLASS attribute,
#: not an instance one, because the posture has to be readable WITHOUT constructing the adapter:
#: the seeded-persona adapter refuses to construct under an inherited profile, and a posture
#: that can only be computed by constructing something disappears exactly when it matters most.
END_USER_AUTH_ATTR = "end_user_auth"


def declared_end_user_auth(adapter: object) -> str:
    """What ``adapter`` (a class or an instance) declares, defaulting to :data:`CLIENT_ASSERTED`.

    The default is the fail-closed one in BOTH directions this value is read: it withholds the
    "authenticated" verdict the exposure guard would relax on, and it claims nothing about an
    adapter that never spoke. An unrecognised value lands in the same place, so a typo in a
    declaration cannot read as a verification claim.
    """
    declared = getattr(adapter, END_USER_AUTH_ATTR, None)
    if isinstance(declared, str) and declared in END_USER_AUTH_KINDS:
        return declared
    return CLIENT_ASSERTED


class EndUserAuthUnavailableError(IdentityError):
    """This deployment can authenticate NO end user at all, and the message says why.

    A plain :class:`~hex_service_kit.identity.IdentityError` means THIS caller did not
    authenticate; another one might. This means the bound adapter cannot authenticate anybody:
    a placeholder that resolves nobody, or an adapter that refused to construct because the
    posture it needs was never chosen.

    The distinction is worth a type because the two need different answers. The commons request
    dependency maps every ``IdentityError`` to a bare 401 carrying "authentication required",
    which sends an operator hunting for a missing credential when the truth is in the
    configuration and no credential would have helped. Subclasses carry their own
    :attr:`http_status` and their own message, and ``api/app.py`` answers with both.
    """

    #: The status the API answers with. 401 is right where a caller could have authenticated
    #: and did not; a subclass meaning "nobody can, here" says so with a different code.
    http_status: int = 401
