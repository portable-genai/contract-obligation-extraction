"""The loopback bound is a property of the APP OBJECT, not of ``main()``.

The defect this guards is invisible to a test that only calls ``main()`` or only reads
``resolve_bind_host``: the Dockerfile ``CMD`` and the Makefile ``run-api`` target serve the
``app`` object, so a bound that lives only in ``main()`` never runs in a shipped process.

The second half is the posture the app object is BUILT with, and it is the reason this file
re-imports the module under a scrubbed environment. An app assembled while the profile variable
is absent must not be indistinguishable from one assembled under a deliberate ``local``: same
CORS allowlist, same ``X-Dev-Persona`` header, same open S2S path, and, with an S2S token set,
an exposure guard switched OFF. That is a production deployment whose profile variable went
missing answering a stranger on the LAN with a seeded approver persona. Every route must refuse
instead, and "every" includes ``/healthz`` and the agent card: a deployment nobody configured
has no business being reachable at all.

The third half, and the reason the second was not enough: SETTING
``CONTRACT_S2S_TOKEN`` used to switch the guard off under a DELIBERATE
``local`` too, because the guard only ever covered the zero-secret demo. That is an ordinary
deployment shape, not a misconfiguration, and it served a LAN peer the seeded persona list and a
real triage decision. A service credential authenticates a calling SERVICE and no end user, so
the guard now reads the identity BINDING instead (see
``tests/unit/test_end_user_auth_posture.py`` for the derivation and its drift guard). Both
directions are proved below: the seeded-persona and unimplemented bindings refuse a LAN peer
whatever the token says, and a VERIFYING binding stands the guard down, which is the control
that keeps the first claim from being true for the boring reason.

The three-state resolution behind these postures is proved in
``tests/unit/test_profile_single_source.py``; here it is spent on real requests.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from hex_service_kit.netdefaults import InsecureCorsError

from contract_obligation_extraction.api.app import (
    app,
)

from tests import REPO_ROOT
from tests.conftest import reimport

_PROFILE_ENV = "CONTRACT_PROFILE"
_CORS_ORIGINS_ENV = "CONTRACT_CORS_ORIGINS"
_TOKEN_ENV = "CONTRACT_S2S_TOKEN"
_INSECURE_DEMO_ENV = "CONTRACT_ALLOW_INSECURE_DEMO"
_IAP_AUDIENCE_ENV = "CONTRACT_IAP_AUDIENCE"

#: The API module, named once. Built as a constant rather than inlined at each call site so
#: `ruff format` produces the same result whatever `package_name` a repo is rendered with.
_API_MODULE = "contract_obligation_extraction.api.app"

#: A peer on the LAN. RFC 5737 documentation address: no real host, and obviously fictional.
LAN_PEER = "192.0.2.50"

#: Everything the app serves. The unconsented posture must refuse ALL of it, including the two
#: routes that need no identity at all, so this list is the definition of "every route".
EVERY_ROUTE: tuple[tuple[str, str], ...] = (
    ("GET", "/healthz"),
    ("GET", "/v1/personas"),
    ("GET", "/.well-known/agent-card.json"),
    ("POST", "/v1/triage"),
    ("POST", "/v1/audit/ping"),
)


def _client(peer: str, target: Any = app) -> TestClient:
    return TestClient(target, client=(peer, 50000))


def _call(client: TestClient, method: str, path: str) -> httpx.Response:
    if method == "GET":
        return client.get(path, headers={"X-Dev-Persona": "approver"})
    return client.post(
        path,
        json={"subject": "Acme (FICTIONAL)", "text": "urgent data breach"},
        headers={"X-Dev-Persona": "approver"},
    )


def test_lan_peer_is_refused_on_a_browser_facing_route() -> None:
    """A LAN peer reaching the unauthenticated local posture gets 503, not a seeded persona."""
    resp = _client(LAN_PEER).post(
        "/v1/triage",
        json={"subject": "Acme (FICTIONAL)", "text": "urgent data breach"},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 503
    assert "non-loopback peer" in resp.json()["detail"]


def test_loopback_peer_still_serves_the_local_demo() -> None:
    """The guard must not break the offline demo it exists to protect."""
    assert _client("127.0.0.1").get("/healthz").status_code == 200


def test_a_forwarding_header_disqualifies_even_a_loopback_peer() -> None:
    """A proxy has already rewritten the scope peer, so the header's presence is disqualifying."""
    resp = _client("127.0.0.1").get("/healthz", headers={"X-Forwarded-For": "127.0.0.1"})
    assert resp.status_code == 503
    assert "forwarding header" in resp.json()["detail"]


def test_the_documented_opt_out_restores_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """The operator can accept the exposure explicitly; nothing else may."""
    monkeypatch.setenv(_INSECURE_DEMO_ENV, "1")
    assert _client(LAN_PEER).get("/healthz").status_code == 200


def test_the_shipped_entry_points_serve_the_app_object() -> None:
    """If this ever stops being true, a bound living in main() would be enough. It is not."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "api.app:app" in dockerfile
    assert "run-api" in makefile


# --------------------------------------------------------------------------------------- #
# The unconsented posture: the profile variable is ABSENT and an S2S token IS set. This is the
# exact shape of a production deploy whose profile variable went missing from the environment.
# --------------------------------------------------------------------------------------- #
@pytest.fixture()
def unconsented_app(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The API module assembled with NO profile variable and an S2S token present.

    Re-imported rather than monkeypatched after the fact, because the postures under test are
    decided at import: that is the point of resolving once, at module scope.
    """
    monkeypatch.delenv(_PROFILE_ENV, raising=False)
    monkeypatch.setenv(_TOKEN_ENV, "s3cret-not-real")
    monkeypatch.delenv(_INSECURE_DEMO_ENV, raising=False)
    return reimport(_API_MODULE)


@pytest.mark.parametrize(("method", "path"), EVERY_ROUTE, ids=[p for _, p in EVERY_ROUTE])
def test_an_unconsented_deployment_refuses_every_route_to_a_lan_peer(
    unconsented_app: ModuleType, method: str, path: str
) -> None:
    """Setting the S2S token must not switch the exposure guard off for a deploy nobody chose."""
    resp = _call(_client(LAN_PEER, unconsented_app.app), method, path)
    assert resp.status_code == 503, f"{method} {path} answered {resp.status_code}"
    detail = resp.json()["detail"]
    assert "non-loopback peer" in detail
    # The refusal names the posture, so the operator can tell an unconfigured deploy from a
    # deliberate offline demo without reading the source.
    assert "unconfigured" in detail


def test_an_unconsented_deployment_refuses_a_dev_persona_even_on_loopback(
    unconsented_app: ModuleType,
) -> None:
    """The seeded personas are refused at the ADAPTER too, so loopback is not a way in."""
    resp = _client("127.0.0.1", unconsented_app.app).post(
        "/v1/triage",
        json={"subject": "Acme (FICTIONAL)", "text": "urgent data breach"},
        headers={"X-Dev-Persona": "approver"},
    )
    assert resp.status_code == 401


def test_an_unconsented_deployment_refuses_the_s2s_route_even_on_loopback(
    unconsented_app: ModuleType,
) -> None:
    """No profile means no authentication scheme was chosen, so there is nothing to check."""
    resp = _client("127.0.0.1", unconsented_app.app).post("/v1/audit/ping")
    assert resp.status_code == 401
    assert "no authentication scheme" in resp.json()["detail"]


# --------------------------------------------------------------------------------------- #
# The refuted deployment: ``local`` chosen DELIBERATELY with the S2S token SET. Not a
# misconfiguration, an ordinary shape, and the one a laxer guard stands down for.
# --------------------------------------------------------------------------------------- #
def _app_under(monkeypatch: pytest.MonkeyPatch, profile: str, token: str | None) -> ModuleType:
    """Re-import the API module with the given profile and token, and no insecure-demo opt-out."""
    monkeypatch.setenv(_PROFILE_ENV, profile)
    if token is None:
        monkeypatch.delenv(_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(_TOKEN_ENV, token)
    monkeypatch.delenv(_INSECURE_DEMO_ENV, raising=False)
    return reimport(_API_MODULE)


@pytest.fixture()
def local_with_service_token(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return _app_under(monkeypatch, "local", "s3cret-not-real")


@pytest.mark.parametrize(("method", "path"), EVERY_ROUTE, ids=[p for _, p in EVERY_ROUTE])
def test_a_service_token_does_not_open_the_end_user_routes_to_a_lan_peer(
    local_with_service_token: ModuleType, method: str, path: str
) -> None:
    """The exact refutation: a credential for SERVICES must not unbound END-USER routes."""
    resp = _call(_client(LAN_PEER, local_with_service_token.app), method, path)
    assert resp.status_code == 503, f"{method} {path} answered {resp.status_code}"
    detail = resp.json()["detail"]
    assert "non-loopback peer" in detail
    # The posture named is the deliberate ``local`` one, not ``unconfigured``: this deployment
    # WAS configured, and its seeded personas are still not end-user authentication.
    assert "'local'" in detail


def test_the_zero_secret_demo_is_bounded_exactly_as_the_token_bearing_one_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The token is not part of the decision, so removing it must change nothing out here."""
    app_without_token = _app_under(monkeypatch, "local", None)
    resp = _call(_client(LAN_PEER, app_without_token.app), "POST", "/v1/triage")
    assert resp.status_code == 503


def test_the_local_demo_still_works_on_loopback_with_a_service_token_set(
    local_with_service_token: ModuleType,
) -> None:
    """The guard must not break the offline demo, and a token must not narrow it either."""
    resp = _call(_client("127.0.0.1", local_with_service_token.app), "POST", "/v1/triage")
    assert resp.status_code == 200
    assert resp.json()["requires_human_review"] is True


# --------------------------------------------------------------------------------------- #
# The control: a VERIFYING identity binding stands the guard down. Without this, "everything
# refuses a LAN peer" would be satisfied by a guard that is simply always on, which is not a
# working service and would prove nothing about the derivation.
# --------------------------------------------------------------------------------------- #
@pytest.fixture()
def verifying_identity(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The managed profile, whose identity adapter verifies a signed IAP assertion."""
    return _app_under(monkeypatch, "gcp", "s3cret-not-real")


def test_a_verifying_identity_binding_lets_the_service_be_reached(
    verifying_identity: ModuleType,
) -> None:
    """A fronted deployment must stay health-checkable, or nothing could ever be deployed."""
    assert _client(LAN_PEER, verifying_identity.app).get("/healthz").status_code == 200


def test_but_its_end_user_route_still_refuses_an_uncredentialed_lan_peer(
    verifying_identity: ModuleType,
) -> None:
    """The guard stands down because the ROUTE authenticates, so the route had better do it.

    The declaration is a claim the adapter makes about itself; this is the claim being cashed.
    No IAP assertion header means no verified principal, and the seeded-persona header carries
    no weight at all outside the seeded-persona binding.

    503 rather than 401 here because this fixture configures no IAP audience, and an
    unconfigured audience is a deployment that can authenticate NOBODY: verifying without an
    audience is not a fallback the adapter has (google-auth documents ``audience=None`` as "the
    audience is not verified", which accepts any Google-signed token from any project). The
    401 path, where the deployment is configured and only THIS caller failed, is the test
    below. Both are refusals and neither is a 500; which one is returned is the difference
    between "fix your request" and "fix your deployment".
    """
    resp = _call(_client(LAN_PEER, verifying_identity.app), "POST", "/v1/triage")
    assert resp.status_code == 503
    assert _IAP_AUDIENCE_ENV in resp.json()["detail"], "the refusal must name what to configure"
    assert _client(LAN_PEER, verifying_identity.app).get("/v1/personas").json() == []


def test_a_configured_verifying_profile_answers_401_to_a_peer_with_no_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured half: this deployment CAN authenticate, and this caller did not.

    Without this, the 503 above would be satisfied by an adapter that refuses everything, and
    "the end-user route refuses an uncredentialed peer" would be true for the boring reason.
    """
    monkeypatch.setenv(_IAP_AUDIENCE_ENV, "/projects/000000000000/global/backendServices/1")
    module = _app_under(monkeypatch, "gcp", "s3cret-not-real")
    resp = _call(_client(LAN_PEER, module.app), "POST", "/v1/triage")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "authentication required"


# --------------------------------------------------------------------------------------- #
# The unimplemented binding: bounded like any other posture that authenticates nobody, and
# refusing with a status and a reason rather than a bare 500.
# --------------------------------------------------------------------------------------- #
@pytest.fixture()
def unimplemented_identity(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return _app_under(monkeypatch, "onprem", "s3cret-not-real")


def test_an_unimplemented_identity_binding_refuses_a_lan_peer(
    unimplemented_identity: ModuleType,
) -> None:
    resp = _call(_client(LAN_PEER, unimplemented_identity.app), "POST", "/v1/triage")
    assert resp.status_code == 503
    assert "'onprem'" in resp.json()["detail"]


def test_an_unimplemented_identity_binding_answers_a_status_and_a_reason_not_a_bare_500(
    unimplemented_identity: ModuleType,
) -> None:
    """Raising ``NotImplementedError`` here would not be an ``IdentityError``.

    Nothing would handle it, so FastAPI would answer 500 with no body: the caller gets nothing
    to act on and the operator gets nothing to read. The placeholder refuses like the local
    adapter refuses, and says what to bind and where.
    """
    resp = _call(_client("127.0.0.1", unimplemented_identity.app), "POST", "/v1/triage")
    assert resp.status_code == 501, "no credential would have helped, so 401 would be a lie"
    assert "docs/onprem-migration.md" in resp.json()["detail"]


_DEV_ORIGIN = "http://localhost:3000"


def test_a_deliberate_local_run_does_grant_the_dev_cors_origin() -> None:
    """The control for the test below: the relaxation is real, so its absence means something."""
    resp = _client("127.0.0.1").get("/healthz", headers={"Origin": _DEV_ORIGIN})
    assert resp.headers.get("access-control-allow-origin") == _DEV_ORIGIN
    assert "strict-transport-security" not in resp.headers, "local terminates no TLS"


def test_an_unconsented_deployment_grants_no_dev_cors_and_gets_the_hardened_headers(
    unconsented_app: ModuleType,
) -> None:
    """Relaxations key off ``exposure_profile``, so an unconsented run gets none of them.

    Asserted on the wire rather than by reading the middleware stack: what a browser is told is
    the thing that matters, and a header that is computed correctly but never emitted is the
    defect this whole file exists for.
    """
    resp = _client("127.0.0.1", unconsented_app.app).get(
        "/healthz", headers={"Origin": _DEV_ORIGIN}
    )
    assert resp.status_code == 200, "loopback is still served; only the relaxations are withdrawn"
    assert "access-control-allow-origin" not in resp.headers, (
        "an unconsented run inherited the localhost dev CORS allowlist"
    )
    assert "strict-transport-security" in resp.headers, (
        "an unconsented run is not the local profile, so it takes the hardened header baseline"
    )


#: One real origin, named in full, which is the only kind of entry an allowlist may hold.
_NAMED_ORIGIN = "https://tenant.example.com"


def test_a_named_origin_boots_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the test below: a configured allowlist is honoured, so a refusal means
    the wildcard was refused and not that this profile simply cannot import.
    """
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(_CORS_ORIGINS_ENV, _NAMED_ORIGIN)
    module = reimport(_API_MODULE)
    resp = _client("127.0.0.1", module.app).get("/healthz", headers={"Origin": _NAMED_ORIGIN})
    assert resp.headers.get("access-control-allow-origin") == _NAMED_ORIGIN


def test_a_configured_wildcard_origin_refuses_to_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wildcard in this repo's own allowlist is a BOOT failure, not a later surprise.

    A commons that hands a configured ``*`` straight back as a single explicit origin,
    despite documenting that it never returns one, is a trap. This app pairs that list with
    ``allow_credentials=True``, and Starlette reads allow-all plus credentials as
    echo-the-request-origin, so the pass-through is a credentialed any-origin policy: the
    signed-in session offered to every site on the internet.

    The call sits at MODULE scope, next to the exposure guard and for the same reason, so an
    operator who configures a wildcard gets a process that refuses to come up rather than one
    that serves and quietly trusts everybody. Owned here rather than only in the commons because
    it is this app's exposure, and a property nobody asserts locally is a property that can be
    un-pinned upstream without a single test in this repo going red.
    """
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(_CORS_ORIGINS_ENV, "*")
    with pytest.raises(InsecureCorsError):
        reimport(_API_MODULE)


# --------------------------------------------------------------------------------------- #
# The interactive docs are part of the exposure, and they are withdrawn with it.
#
# Under `gcp`, the ONE profile whose guard deliberately stands down and whose process really
# does bind every interface, an uncredentialed LAN peer received GET /docs and GET
# /openapi.json as 200: the complete route inventory, every request and response schema and
# every field name, handed to a caller who can reach none of those routes. Swagger UI is a
# development affordance, so it is served under the DELIBERATE offline profile and nowhere
# else. See the module docstring of `api/app.py` for why there is no opt-in variable.
# --------------------------------------------------------------------------------------- #
_DOC_ROUTES: tuple[str, ...] = ("/docs", "/redoc", "/openapi.json")


@pytest.mark.parametrize("path", _DOC_ROUTES)
def test_a_deliberate_local_run_does_serve_the_interactive_docs(path: str) -> None:
    """The control. Without it, "the docs are gone" would be true for the boring reason."""
    assert _client("127.0.0.1").get(path).status_code == 200


@pytest.mark.parametrize("path", _DOC_ROUTES)
def test_the_verifying_profile_serves_no_interactive_docs_to_anybody(
    verifying_identity: ModuleType, path: str
) -> None:
    """Not merely refused to a LAN peer: NOT SERVED, so there is no peer that gets them.

    The guard has stood down here, so a bound on the peer would be no bound at all. The route
    is absent instead, which is the only thing that holds once the process binds 0.0.0.0.
    """
    assert _client(LAN_PEER, verifying_identity.app).get(path).status_code == 404
    assert _client("127.0.0.1", verifying_identity.app).get(path).status_code == 404


@pytest.mark.parametrize("path", _DOC_ROUTES)
def test_an_unconsented_deployment_serves_no_interactive_docs_either(
    unconsented_app: ModuleType, path: str
) -> None:
    """Unset is not consent here either: the relaxation keys off ``exposure_profile``."""
    assert _client("127.0.0.1", unconsented_app.app).get(path).status_code == 404


def test_the_health_route_survives_the_docs_being_withdrawn(
    verifying_identity: ModuleType,
) -> None:
    """`openapi_url=None` removes a ROUTE, not the app. A fronted deploy stays health-checkable."""
    assert _client(LAN_PEER, verifying_identity.app).get("/healthz").status_code == 200
