"""On-prem IdentityPort: fail-fast placeholder for the client's own IdP (OIDC/SAML).

The refusal has a SHAPE, and the shape is the point. A bare ``NotImplementedError`` is not an
:class:`~hex_service_kit.identity.IdentityError`, so it escaped the request dependency's
handling entirely and FastAPI answered a bare 500 with no body: an unauthenticated caller got a
stack-trace-shaped nothing, and an operator got no reason. That is the same defect as an
unhandled failure anywhere else, dressed as a portability placeholder.

So it refuses like the local adapter refuses, with a status and a reason
(``ports/identity.py``'s :class:`EndUserAuthUnavailableError`), and it keeps
:class:`NotImplementedError` in its ancestry because "the exit family raises
``NotImplementedError``" is a claim the contract suite and ``scripts/portability_demo.py``
both make about EVERY port. Both remain true at once.
"""

from __future__ import annotations

from hex_service_kit.identity import Principal, RequestContext

from ...config import Settings
from ...ports.identity import UNIMPLEMENTED, EndUserAuthUnavailableError

_MESSAGE = (
    "on-prem identity is a portability placeholder: no end-user identity provider is bound, so "
    "this deployment can authenticate nobody. Bind the client's OIDC/SAML IdP adapter in "
    "config/settings.yaml under adapters.identity.onprem (see docs/onprem-migration.md), or "
    "run a profile whose identity adapter verifies an assertion."
)


class OnPremIdentityUnimplementedError(EndUserAuthUnavailableError, NotImplementedError):
    """The on-prem identity placeholder was called; no IdP is bound.

    Two ancestries, both load-bearing. As the port's
    :class:`EndUserAuthUnavailableError` (see ``ports/identity.py``) it
    carries a status and a reason to the caller instead of a bare 500. As a
    :class:`NotImplementedError` it keeps the exit family's uniform refusal, which the contract
    suite and the portability demo assert for every port at once.

    501, not 401: no credential the caller could have presented would have worked, so inviting
    them to authenticate would be a lie. Nothing is implemented here yet, and the status says
    exactly that.
    """

    http_status = 501


class OnPremIdentityAdapter:
    """Satisfies IdentityPort but refuses at call time: the client wires its own IdP."""

    #: Resolves nobody until an IdP is bound, so the exposure guard treats this deployment as
    #: unauthenticated and keeps it on loopback. See ``ports/identity.py``.
    end_user_auth = UNIMPLEMENTED

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve(self, ctx: RequestContext) -> Principal:
        raise OnPremIdentityUnimplementedError(_MESSAGE)
