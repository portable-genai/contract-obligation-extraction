"""FastAPI application for Contract Obligation Extraction (Rgc12).

Import-safe (the Container is built at request time, never at import; only ``Settings`` is read
at import, to learn which identity adapter is bound, and no adapter is constructed), identity is
a server-verified Principal (the client-asserted actor is discarded), S2S callers are
authenticated fail-closed, and the fail-closed network defaults come from the commons: a profile
that cannot authenticate an end user binds loopback unless explicitly opted out, and CORS never
falls back to ``*``.

The profile is resolved ONCE, by ``config.resolve_profile``, and an absent
``CONTRACT_PROFILE`` is NO CHOICE rather than a silent ``local``. Every
posture decision here keys off that one resolution, through the derived member that fails closed
in the right direction:

* the RELAXATIONS (CORS allowlist, the ``X-Dev-Persona`` allowed header, the HSTS baseline, the
  S2S scheme) key off ``exposure_profile``, where an unconsented run is ``unconfigured`` and
  therefore gets none of them;
* the RESTRICTION (the loopback bound) keys off ``bind_profile``, where an unconsented run is
  ``local`` and therefore stays on loopback.

One string could not do both: handing the relaxations ``local`` would grant a dev CORS
allowlist and the persona header to a deploy whose profile variable went missing, and handing
the restriction ``unconfigured`` would let that same deploy bind every interface.

The loopback bound lives on the APP OBJECT, not in ``main()``. The Dockerfile ``CMD`` and the
Makefile ``run-api`` target serve ``app`` directly, so a guard reachable only from ``main()``
never runs in a shipped process. ``add_loopback_exposure_guard`` is therefore registered at
module scope below, and ``resolve_bind_host`` in ``main()`` is the second layer rather than the
only one.

WHAT SWITCHES THE EXPOSURE GUARD OFF is one thing and one thing only: the identity adapter
bound to the identity port declaring that it VERIFIES the end user (see ``ports/identity.py``).
The guard exists to bound routes that answer an end user with no credential, so the question it
has to settle is whether an end user CAN be authenticated here, and only the bound adapter
knows. Deriving it from the profile string plus the presence of
``CONTRACT_S2S_TOKEN`` is wrong in the most dangerous direction:
that secret authenticates a calling SERVICE and no end user at all, so SETTING it disabled the
guard for exactly the end-user routes it was protecting. A LAN peer with no Authorization
header and no ``X-Dev-Persona`` then got the seeded persona list and a real triage decision.

THE INTERACTIVE DOCS ARE PART OF THAT EXPOSURE, and they are switched off with it. Under the one
profile whose guard deliberately stands down, an uncredentialed LAN peer would receive ``/docs``
and ``/openapi.json`` as 200: the complete route inventory, every request and response schema and
every field name, handed to a caller who cannot reach a single one of those routes. That is
reconnaissance with no counterpart benefit. Swagger UI and the raw OpenAPI document are a
development affordance, so they are served under the DELIBERATE offline ``local`` profile and
nowhere else (see ``_DOCS_URL`` below). There is deliberately no opt-in variable to re-enable
them: another three-state posture switch is another thing to get wrong, the schema is generated
from this file and available to anyone with the repo, and a deployment that wants to publish it
can serve the artifact from somewhere that is not the authenticated service.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from hex_service_kit.identity import IdentityError, IdentityPort, Principal, RequestContext
from hex_service_kit.logging import configure_logging
from hex_service_kit.netdefaults import cors_allowlist, resolve_bind_host
from hex_service_kit.web import (
    add_loopback_exposure_guard,
    add_security_headers,
    make_require_service_caller,
)

from ..config import (
    LOCAL_PROFILE,
    Container,
    ProfileChoice,
    Settings,
    build_container,
    end_user_auth_kind,
    resolve_profile,
)
from ..domain.contracts import CrossTenantError, authorize_contract_access
from ..domain.corpus import AS_OF, contract_by_id
from ..domain.models import TriageInput
from ..domain.triage_service import TriageService
from ..flow import run_contract_register

# Resolved at import, so an unknown, mis-capitalised or deliberately emptied profile is a BOOT
# failure rather than a first-request failure (a serving process must not come up on a profile
# nobody defined).
from ..managed_readiness import assert_managed_profile_ready
from ..ports.identity import VERIFIED, EndUserAuthUnavailableError
from .schemas import (
    HealthResponse,
    RegisterRequest,
    RegisterResponse,
    TriageRequest,
    TriageResponse,
)

_CHOICE = resolve_profile()

# Every environment NAME this module hands to the commons, hoisted to constants. They are
# constants rather than literals at the call sites so that `ruff format` produces the same
# result whatever `env_prefix` a repo is rendered with: a long prefix inlined into a call
# argument pushes the line past the limit and would need a DIFFERENT formatting, which is a
# rendered repo failing its own format check on nothing but the length of its name.
_TOKEN_ENV = "CONTRACT_S2S_TOKEN"
_INSECURE_DEMO_ENV = "CONTRACT_ALLOW_INSECURE_DEMO"
_CORS_ORIGINS_ENV = "CONTRACT_CORS_ORIGINS"
_ALLOWED_CALLERS_ENV = "CONTRACT_S2S_ALLOWED_CALLERS"
_AUDIENCE_ENV = "CONTRACT_S2S_AUDIENCE"
_API_HOST_ENV = "CONTRACT_API_HOST"


@lru_cache(maxsize=1)
def _container() -> Container:
    return build_container(Settings.load())


def _identity() -> IdentityPort:
    return _container().identity


def _request_choice(request: Request) -> ProfileChoice:
    """The app's own resolution, so a test app carrying a different one is honoured."""
    choice = getattr(request.app.state, "profile_choice", None)
    return choice if isinstance(choice, ProfileChoice) else _CHOICE


def get_principal(request: Request) -> Principal:
    """Resolve the VERIFIED end-user principal, or refuse with a status AND a reason.

    The client-asserted actor in the request body is never read; identity flows from here.

    ``hex_service_kit.web.make_get_principal`` is not used, deliberately. It collapses every
    :class:`~hex_service_kit.identity.IdentityError` into a bare 401 carrying "authentication
    required", which is the right answer for a caller who could have authenticated and did not,
    and the wrong one for a deployment that can authenticate NOBODY. An operator reading that
    401 goes looking for a missing credential when the truth is that the bound adapter is an
    unimplemented placeholder or refused to construct at all, and no credential would have
    helped. Those cases raise ``ports/identity.py``'s
    :class:`EndUserAuthUnavailableError`, which carries its own status and its own message, and
    this is where the two are told apart.
    """
    try:
        identity = _identity()
        ctx = RequestContext(headers={k.lower(): v for k, v in request.headers.items()})
        return identity.resolve(ctx)
    except EndUserAuthUnavailableError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        ) from exc


_authenticate_service_caller = make_require_service_caller(
    lambda request: _request_choice(request).exposure_profile,
    token_env=_TOKEN_ENV,
    allowed_callers_env=_ALLOWED_CALLERS_ENV,
    audience_env=_AUDIENCE_ENV,
)


def require_service_caller(request: Request) -> None:
    """Authenticate the calling SERVICE, refusing to decide at all without a chosen profile.

    The commons dependency picks its scheme from the profile string: a Google-signed OIDC ID
    token under a secure profile, the shared-secret bearer otherwise. The shared-secret path
    stays OPEN when ``CONTRACT_S2S_TOKEN`` is unset (loopback dev with zero
    secrets), so an UNSET ``CONTRACT_PROFILE`` must never be allowed to
    select it: that combination is an unauthenticated write path on a deploy nobody configured.
    When no profile was chosen, no scheme was chosen either, and the answer is 401.

    Known limit, stated rather than papered over: with the profile set to ``local``
    DELIBERATELY and no S2S secret, these endpoints remain unauthenticated. That is the offline
    demo posture, and it is bounded by EXPOSURE rather than by this dependency (the guard on the
    app object below), not left open.

    SETTING the secret closes this dependency and nothing else. It does not make the end-user
    routes authenticated and it does not relax the exposure guard, which reads the identity
    binding and never this variable. Under the ``local`` profile the guard therefore keeps the
    whole app, S2S routes included, on loopback: this token is a shared secret in a
    seeded-persona demo posture, not a reason to accept LAN callers. Choose a profile whose
    identity adapter verifies an assertion for that, or opt in with
    ``CONTRACT_ALLOW_INSECURE_DEMO=1``.
    """
    if not _request_choice(request).service_auth_configured:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "service-to-service authentication is unconfigured: "
                "CONTRACT_PROFILE is not set, so no authentication scheme "
                "has been chosen"
            ),
        )
    _authenticate_service_caller(request)


# Every relaxation below keys off ``exposure_profile``, never the raw profile: an unset profile
# variable is not consent, so it gets no CORS allowlist, no dev-persona header and HSTS on.
_EXPOSURE = _CHOICE.exposure_profile

#: Service name on every log line and every span. The repo slug: stable, greppable,
#: and the same string the tracer reports as `service.name`.
_SERVICE_NAME = "contract-obligation-extraction"

# Configured at MODULE scope for the same reason the exposure guard is bound there:
# the Dockerfile CMD and `make run-api` serve the app OBJECT, so anything living only
# inside main() never runs in a shipped process.
configure_logging(_EXPOSURE, service=_SERVICE_NAME)

# The interactive docs are a RELAXATION, so they key off the same string as every other one and
# an unconsented run gets none of them either. `openapi_url=None` removes the schema route, and
# Swagger UI and ReDoc both fetch that schema, so this is ONE decision rather than three that
# could disagree. See the module docstring for why there is no opt-in variable to re-enable it.
_DOCS_SERVED = _EXPOSURE == LOCAL_PROFILE
_OPENAPI_URL = "/openapi.json" if _DOCS_SERVED else None
_DOCS_URL = "/docs" if _DOCS_SERVED else None
_REDOC_URL = "/redoc" if _DOCS_SERVED else None

#: The OpenAPI title and description. Each rendered value sits alone on its own line and the
#: sentence is assembled from them, rather than being written out inline: a long friendly_name
#: and a long region on ONE line push it past the 100 column limit `make lint` enforces, and a
#: literal is not something `ruff format` can wrap for us.
_APP_TITLE = "Contract Obligation Extraction"
_APP_REGION = "asia-southeast1"
_APP_DESCRIPTION = _APP_TITLE + ". Region " + _APP_REGION + "."

app = FastAPI(
    title=_APP_TITLE,
    version="0.1.0",
    description=_APP_DESCRIPTION,
    openapi_url=_OPENAPI_URL,
    docs_url=_DOCS_URL,
    redoc_url=_REDOC_URL,
)
app.state.profile_choice = _CHOICE
app.state.profile = _CHOICE.profile

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowlist(_EXPOSURE, origins_env=_CORS_ORIGINS_ENV),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
    + (["X-Dev-Persona"] if _EXPOSURE == LOCAL_PROFILE else []),
)
add_security_headers(app, profile=_EXPOSURE)

# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and the
# guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme OR an S2S scheme;
#      the seeded-persona adapter refuses to construct and every S2S route answers 401, but
#      /healthz and the agent card would still answer a stranger, and a deployment in that state
#      has no business being reachable at all. It is also the one case where a settings file
#      that bound a verifying adapter under `local` must NOT buy the relaxation: unset is not
#      consent, whatever the binding says;
#   2. the identity adapter the active binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on a header the caller wrote (client-asserted) and the on-premises
#      placeholder resolves nobody at all (unimplemented); neither authenticates anyone, so
#      neither may switch this off.
#
# Note what is NOT in this expression: CONTRACT_S2S_TOKEN. A service
# credential is evidence about a calling SERVICE and says nothing about the end-user routes, so
# setting one must not, and now cannot, disable their bound. The S2S routes are bounded by
# `require_service_caller` above, which is where a service credential belongs.
_END_USER_AUTH = end_user_auth_kind()
_END_USER_AUTHENTICATED = _CHOICE.explicit and _END_USER_AUTH == VERIFIED

# The RESTRICTION's profile string. `bind_profile` already reads an unconsented run as `local`
# (the confined case); this widens the same rule to every posture that cannot authenticate an
# end user, so the start-up bound in `main()` and the request-time guard below agree instead of
# one binding every interface while the other refuses every caller on it.
_BIND_PROFILE = _CHOICE.bind_profile if _END_USER_AUTHENTICATED else LOCAL_PROFILE

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline and before any route or dependency runs. Bound to the app
# object so it holds under `uvicorn ...:app --host 0.0.0.0` as well as under `main()`.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    insecure_demo_env=_INSECURE_DEMO_ENV,
    posture=_EXPOSURE,
)


@app.post("/v1/triage", response_model=TriageResponse, tags=["artifacts"])
def triage(
    request: TriageRequest,
    principal: Annotated[Principal, Depends(get_principal)],
) -> TriageResponse:
    """Triage a case; the audit actor is the verified principal, never the request body.

    Rule R8: a result that sets ``requires_human_review`` is ROUTED to the Hrz7 console here,
    in the same request that produced it. Setting the flag is not the escalation; routing is.
    The maker is the verified principal, so the console records who originated the decision.
    """
    container = _container()
    service = TriageService(container.audit, container.tracer)
    result = service.triage(
        TriageInput(subject=request.subject, text=request.text),
        actor=principal.actor,
    )
    review_ref = ""
    if result.requires_human_review:
        review_ref = container.review_router.route(
            result, maker=principal.actor, tenant=principal.tenant
        )
    return TriageResponse.from_domain(result, review_ref=review_ref)


@app.post("/v1/register", response_model=RegisterResponse, tags=["artifacts"])
def register(
    request: RegisterRequest,
    principal: Annotated[Principal, Depends(get_principal)],
) -> RegisterResponse:
    """Read a contract into its obligation register; the consequential result is ROUTED to Hrz7.

    The bound extraction model PROPOSES candidate obligations, dates and risk flags; the
    deterministic engine (obligation-register-kit plus this repo's segmentation, taxonomy and
    renewal clock) OWNS admission, so a candidate citing an unreal clause is dropped, the flags
    are validated against the taxonomy, and the severity band is pure code. The bound generation
    model only narrates, and the note is discarded unless it validates and every figure in it is
    one the engine produced. Rule R8: a register carrying any material finding escalates and is
    routed here, in the same request, with the verified principal as the maker.

    The contract is tenant-owned: the read is authorised against the VERIFIED principal's tenant,
    and a caller from another tenant is refused with 403 (never 404). The client-asserted actor
    and tenant never enter this decision; ``principal`` came from the identity port.
    """
    contract = contract_by_id(request.contract_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no contract {request.contract_id!r} in the corpus",
        )
    try:
        authorize_contract_access(principal.tenant, contract_tenant=contract.tenant)
    except CrossTenantError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    as_of = date.fromisoformat(request.as_of) if request.as_of else AS_OF
    outcome = run_contract_register(
        _container(), contract, as_of=as_of, actor=principal.actor, tenant=principal.tenant
    )
    return RegisterResponse.from_domain(
        outcome.register, note=outcome.note, review_ref=outcome.review_ref
    )


@app.post("/v1/audit/ping", dependencies=[Depends(require_service_caller)], tags=["ops"])
def audit_ping() -> dict[str, bool]:
    """A stand-in S2S endpoint, guarded by fail-closed calling-service authentication."""
    return {"ok": True}


@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    settings = _container().settings
    return HealthResponse(status="ok", profile=settings.profile, region=settings.region)


@app.get("/.well-known/agent-card.json", tags=["ops"])
def agent_card() -> dict[str, object]:
    """Serve the A2A discovery card (rule R4: a deployed agent is discoverable and registered).

    Built from the same tool table the agent runtime binds, so the card cannot advertise a skill
    the service does not implement. It carries no secret and no per-caller data.
    """
    from ..agent.agent_card import agent_card_document

    return agent_card_document(_container().settings)


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local).

    The seeded-persona adapter REFUSES to construct when the local profile was inherited rather
    than chosen, so this reports that refusal as a 503 with its reason instead of a bare 500: a
    picker that silently shows nothing looks like a UI bug, not the configuration error it is.
    """
    try:
        identity = _container().identity
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


def main() -> None:
    """Run the API locally with uvicorn; fail-closed loopback bind whenever no end user can auth."""
    assert_managed_profile_ready(_CHOICE.profile, Settings.load().adapters)

    import uvicorn

    # ``_BIND_PROFILE``, not ``exposure_profile``: this guard treats ``local`` as the RESTRICTIVE
    # case (loopback only), so an unconsented run, and any other posture with no verified
    # end-user identity, must look like ``local`` here even though an unconsented one looks like
    # ``unconfigured`` to every relaxation above.
    host = resolve_bind_host(
        _BIND_PROFILE,
        host_env=_API_HOST_ENV,
        insecure_demo_env=_INSECURE_DEMO_ENV,
    )
    uvicorn.run(app, host=host, port=int(os.environ.get("PORT", "8080")))


if __name__ == "__main__":
    main()
