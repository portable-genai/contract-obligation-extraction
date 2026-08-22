"""Settings + Container: profile-driven dependency injection (the hexagon wiring).

One env var (``CONTRACT_PROFILE``) selects the adapter family for every
port. ``local`` is the SDK-free offline default (dev/test/CI); ``gcp`` is the managed cloud
stack (SDK imports stay lazy so ``local``/``onprem`` import with no cloud SDK installed);
``onprem`` is the fail-fast portability placeholder. The dotted ``module:Class`` binding table
is the single source of truth, exactly like the reference build, and it lives in
``config/settings.yaml`` so a deployment can rebind a port without a code edit. The table below
is the shipped default that file carries; ``tests/test_settings_file.py`` fails the build if the
two ever disagree, so there is no second place for a binding to hide.

The profile read resolves FOUR outcomes from the three states of one variable, and never folds
two of them together:

* **UNSET** - nobody chose. The adapter family is still ``local`` (the alternative is importing
  cloud SDKs that are not installed), but :attr:`ProfileChoice.explicit` is False, so the
  seeded-persona identity adapter refuses to construct, the S2S dependency has no scheme to
  pick, and every relaxation sees :data:`UNCONSENTED_PROFILE` rather than ``local``.
* **SET AND EMPTY** - an intent WAS expressed and it names no profile. It raises
  :class:`~hex_service_kit.netdefaults.ConfiguredEmptyError`, so it can never inherit the unset
  default. An empty string is not a profile any more than it is a host to bind.
* **SET AND UNKNOWN** raises, including the merely mis-capitalised ``Local`` / ``LOCAL`` /
  ``GCP``: a typo must not silently downgrade the posture, and it must not silently fall
  through to some other family's adapters either.
* **SET AND VALID** selects that family, deliberately.

The result is a frozen :class:`ProfileChoice`, never a bare string, because the RELAXATIONS and
the RESTRICTIONS fail closed in OPPOSITE directions and a single "effective profile" string
would harden one while weakening the other. See :attr:`ProfileChoice.exposure_profile` and
:attr:`ProfileChoice.bind_profile`.

Every ``${VAR}`` reference inside the settings file resolves the same three states: UNSET takes
the ``${VAR:-default}`` default, SET-AND-EMPTY RAISES
:class:`~hex_service_kit.netdefaults.ConfiguredEmptyError` rather than inheriting that default or
collapsing to the empty string (an operator who emptied a value expressed an intent, and it names
nothing), and SET-AND-VALID wins.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from hex_service_kit.identity import IdentityPort
from hex_service_kit.netdefaults import ConfiguredEmptyError, EnvSetting, read_env_setting

from .envread import setting_or_default
from .ports.audit import AuditSinkPort
from .ports.extraction import ExtractionPort
from .ports.generation import GenerationPort
from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth
from .ports.observability import EvaluationGatePort, ObservabilityTracerPort
from .ports.review_router import ReviewRouterPort

_PROFILE_ENV = "CONTRACT_PROFILE"
_SETTINGS_ENV = "CONTRACT_SETTINGS"
_REGION = "asia-southeast1"

#: Where the settings file is looked for when the env var names none. Relative to the process
#: working directory, which is the repo root for ``make`` targets and ``/app`` in the image.
DEFAULT_SETTINGS_PATH = Path("config") / "settings.yaml"

LOCAL_PROFILE = "local"
#: The only profiles this service knows how to bind. Anything else is a configuration error.
KNOWN_PROFILES: tuple[str, ...] = (LOCAL_PROFILE, "gcp", "onprem")

#: The profile string handed to every RELAXATION when nobody chose a profile at all. It is
#: deliberately NOT a member of :data:`KNOWN_PROFILES` and it never reaches :class:`Settings` or
#: a binding table: it exists so that "no choice was made" is a distinct input to the security
#: layers rather than being indistinguishable from a deliberately chosen ``local``.
UNCONSENTED_PROFILE = "unconfigured"


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo.

    The comparison is exact and case-sensitive on purpose: every posture decision downstream
    matches the profile string exactly, so ``Local`` selects none of the relaxations but also
    none of the restrictions. Normalising the case here would turn a typo into a silent choice;
    refusing it turns the typo into a boot failure.
    """
    if profile not in KNOWN_PROFILES:
        raise ValueError(
            f"{_PROFILE_ENV}={profile!r} is not a known profile. "
            f"Set it to one of {', '.join(KNOWN_PROFILES)} (exact case) or leave it unset."
        )
    return profile


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    """The ONE resolution of the profile variable, and what each consumer reads.

    The variable is ``CONTRACT_PROFILE``, named once in
    :data:`_PROFILE_ENV`.

    Every module that needs the profile calls :func:`resolve_profile` and reads one of the
    members below. No module may re-derive the decision with its own
    ``os.environ.get("CONTRACT_PROFILE", "local")``: that fallback reads an
    UNSET variable as consent, which is the fail-open this type exists to remove
    (``tests/unit/test_profile_single_source.py`` fails the build if one reappears).

    The two derived profile strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" string would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent consent this is still ``local`` (the SDK-free
    #: adapters), because the alternative would import cloud SDKs that are not installed; the
    #: local IDENTITY adapter refuses to construct when :attr:`explicit` is False, so an
    #: unconsented run has data adapters but no end-user identity.
    profile: str = LOCAL_PROFILE
    #: Was the profile named DELIBERATELY? Direct construction is deliberate by definition (a
    #: caller named the profile in code), so the default is True and only :func:`resolve_profile`
    #: can produce False.
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every RELAXATION keys off: CORS origins, the dev-persona header, HSTS.

        These decisions grant something extra to ``local``, so an unconsented run must NOT look
        like ``local``: it gets :data:`UNCONSENTED_PROFILE`, which is no origin's allowlist, no
        ``X-Dev-Persona`` and HSTS on.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile every RESTRICTION keys off, where ``local`` is the restrictive case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay on loopback.
        Handing :attr:`exposure_profile` to that guard instead would let an unconfigured deploy
        bind every interface, which is the exact inversion this pair of properties prevents.
        """
        return self.profile if self.explicit else LOCAL_PROFILE

    @property
    def service_auth_configured(self) -> bool:
        """May S2S callers be authenticated at all, or is the decision unconfigured?

        False means no profile was chosen, so neither S2S scheme has been selected and the
        request cannot be authenticated. The API turns this into a 401 rather than letting the
        shared-secret path's zero-secret loopback opening apply (see ``api/app.py``).
        """
        return self.explicit


def _profile_setting(environ: Mapping[str, str] | None) -> EnvSetting:
    """The three-state read of the profile variable, from the process or an injected mapping.

    With no argument the read goes through the commons
    (:func:`~hex_service_kit.netdefaults.read_env_setting`), which is the only reader of
    ``os.environ`` in this module. The injected-mapping form builds the SAME
    :class:`~hex_service_kit.netdefaults.EnvSetting`, so a test drives the identical three
    states rather than a second, kinder implementation of them.
    """
    if environ is None:
        return read_env_setting(_PROFILE_ENV)
    raw = environ.get(_PROFILE_ENV)
    return EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())


def resolve_profile(environ: Mapping[str, str] | None = None) -> ProfileChoice:
    """Resolve the deployment profile into a :class:`ProfileChoice`, three states, never two.

    UNSET is carried forward as "nobody chose" (``explicit=False``) rather than being folded
    into a deliberate ``local``. SET AND EMPTY raises :class:`ConfiguredEmptyError`: it must
    never inherit the unset default, because an operator who emptied the variable expressed an
    intent and it names no profile. SET AND UNKNOWN raises :class:`ValueError`. Only SET AND
    VALID selects a family.

    Called at module scope by ``api/app.py``, so both raises are BOOT failures: a serving
    process that fails to start is a visible outage, while one that answers a request on a
    posture nobody chose is a silent one.
    """
    setting = _profile_setting(environ)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_PROFILE_ENV} is set to an empty value, which is not a profile. A variable that "
            "was deliberately emptied is not the same as an unset one, so it does not inherit "
            f"the offline default. Unset it, or set it to one of {', '.join(KNOWN_PROFILES)}."
        )
    if setting.is_unset:
        return ProfileChoice(profile=LOCAL_PROFILE, explicit=False)
    return ProfileChoice(profile=_validate_profile(setting.value), explicit=True)


#: Resolved ONCE, at import. An unknown, mis-capitalised or deliberately emptied value therefore
#: kills the process before any module can act on a posture nobody chose. Every surface (api,
#: cli, agent, eval) imports this module, so every surface inherits the check.
PROFILE_CHOICE: ProfileChoice = resolve_profile()


# port -> profile -> "module:Class". Every port needs a binding in EVERY known profile (the
# parity test asserts it). There is deliberately no fallback entry: an unknown profile has
# already been refused by ``resolve_profile`` / ``Settings.__post_init__``, so a missing binding
# here is a bug to raise on, not a reason to silently bind some other family's adapters.
#: This package's import root. The targets below are built from it rather than written out in
#: full, so the formatted line length does not depend on how long the package name happens to
#: be: a repo rendered with a longer name must not need a different `ruff format` result.
_PKG = "contract_obligation_extraction"

DEFAULT_BINDINGS: dict[str, dict[str, str]] = {
    "audit": {
        "local": f"{_PKG}.adapters.local.audit:LocalAuditAdapter",
        "gcp": f"{_PKG}.adapters.gcp.audit:CloudAuditAdapter",
        "onprem": f"{_PKG}.adapters.onprem.audit:OnPremAuditAdapter",
    },
    "identity": {
        "local": f"{_PKG}.adapters.local.identity:LocalIdentityAdapter",
        "gcp": f"{_PKG}.adapters.gcp.identity:IapIdentityAdapter",
        "onprem": f"{_PKG}.adapters.onprem.identity:OnPremIdentityAdapter",
    },
    "review_router": {
        "local": f"{_PKG}.adapters.local.review_router:LocalReviewRouter",
        "gcp": f"{_PKG}.adapters.gcp.review_router:CloudReviewRouter",
        "onprem": f"{_PKG}.adapters.onprem.review_router:OnPremReviewRouter",
    },
    "tracer": {
        "local": f"{_PKG}.adapters.local.tracer:LocalNoopTracerAdapter",
        "gcp": f"{_PKG}.adapters.gcp.tracer:CloudTracerAdapter",
        "onprem": f"{_PKG}.adapters.onprem.tracer:OnPremTracerAdapter",
    },
    "evaluation": {
        "local": f"{_PKG}.adapters.local.evaluation:LocalOfflineEvalAdapter",
        "gcp": f"{_PKG}.adapters.gcp.evaluation:ManagedEvalGateAdapter",
        "onprem": f"{_PKG}.adapters.onprem.evaluation:OnPremEvalAdapter",
    },
    "generation": {
        "local": f"{_PKG}.adapters.local.generation:LocalGenerationAdapter",
        "gcp": f"{_PKG}.adapters.gcp.generation:CloudGenerationAdapter",
        "onprem": f"{_PKG}.adapters.onprem.generation:OnPremGenerationAdapter",
    },
    "extraction": {
        "local": f"{_PKG}.adapters.local.extraction:LocalExtractionAdapter",
        "gcp": f"{_PKG}.adapters.gcp.extraction:CloudExtractionAdapter",
        "onprem": f"{_PKG}.adapters.onprem.extraction:OnPremExtractionAdapter",
    },
}

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand(value: str) -> str:
    """Resolve ``${VAR}`` / ``${VAR:-default}`` with a three-state read of each variable.

    The rule is the adapters' rule, one layer down, so there is exactly one implementation of
    it: :func:`~.envread.setting_or_default`. UNSET takes the default written in the file,
    SET-AND-EMPTY raises rather than resolving to the empty string (which for a base URL, an
    allowlist or a path is the permissive branch), and a value wins. ``${VAR}`` with no ``:-``
    carries the empty string as its default, so unset yields empty and emptied still raises.
    """

    def repl(m: re.Match[str]) -> str:
        return setting_or_default(m.group(1), m.group(2) or "")

    return _ENV_REF.sub(repl, value)


def _expanded(node: Any) -> Any:
    """Walk a parsed YAML tree expanding every string scalar."""
    if isinstance(node, str):
        return _expand(node)
    if isinstance(node, dict):
        return {str(k): _expanded(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_expanded(v) for v in node]
    return node


def _read_settings_file(path: Path | None = None) -> dict[str, Any]:
    """Load the settings file, or return ``{}`` when no file is configured or present.

    An EXPLICIT path (argument or ``CONTRACT_SETTINGS``) that does not
    exist raises: somebody named a file, and silently running on built-in defaults instead is
    how a deployment ends up on a configuration nobody chose. The implicit
    ``config/settings.yaml`` is optional, so the package still works installed as a wheel with
    no repo checkout around it.
    """
    explicit = path
    if explicit is None:
        setting = read_env_setting(_SETTINGS_ENV)
        if setting.is_configured_empty:
            raise ValueError(f"{_SETTINGS_ENV} is set but empty; unset it or name a file.")
        if setting.has_value:
            explicit = Path(setting.value)
    target = explicit if explicit is not None else DEFAULT_SETTINGS_PATH
    if not target.exists():
        if explicit is not None:
            raise FileNotFoundError(f"settings file {target} does not exist")
        return {}
    loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"settings file {target} must contain a mapping at the top level")
    return {str(k): _expanded(v) for k, v in loaded.items()}


def _bindings_from(data: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Validate and adopt the file's ``adapters:`` block, or fall back to the shipped default."""
    block = data.get("adapters")
    if block is None:
        return {port: dict(table) for port, table in DEFAULT_BINDINGS.items()}
    if not isinstance(block, dict):
        raise ValueError("settings 'adapters' must be a mapping of port -> profile -> target")
    if set(block) != set(DEFAULT_BINDINGS):
        raise ValueError(
            "settings 'adapters' must bind exactly the declared ports "
            f"{sorted(DEFAULT_BINDINGS)}, got {sorted(block)}"
        )
    out: dict[str, dict[str, str]] = {}
    for port, table in block.items():
        if not isinstance(table, dict) or set(table) != set(KNOWN_PROFILES):
            raise ValueError(
                f"settings 'adapters.{port}' must bind every profile {list(KNOWN_PROFILES)}"
            )
        out[str(port)] = {str(p): str(t) for p, t in table.items()}
    return out


@dataclass(frozen=True, slots=True)
class Settings:
    """Deployment settings, resolved from the settings file and the environment."""

    profile: str = LOCAL_PROFILE
    region: str = _REGION
    audit_path: str = ":memory:"
    #: External head anchor for the WORM audit chain (practices check C9). Keep it on a
    #: DIFFERENT volume, under different credentials, from ``audit_path``: the hash chain alone
    #: cannot detect a truncated tail, because dropping the newest rows leaves a shorter chain
    #: that verifies perfectly. Empty means no anchor, which is right for the ephemeral
    #: ``:memory:`` store and wrong for anything durable.
    audit_anchor_path: str = ""
    #: Base URL of the Hrz7 Human-Review console the R8 producer path submits to.
    review_url: str = ""
    #: The audience the managed IAP identity adapter verifies the signed assertion AGAINST: the
    #: IAP-protected resource, ``/projects/<NUM>/global/backendServices/<ID>`` behind an HTTPS
    #: load balancer. It is CONFIGURATION rather than a literal because it is per-deployment, and
    #: it is read here (through the settings file's three-state expansion) rather than from a
    #: default so that UNSET and SET-AND-EMPTY both arrive as ``""``. Empty means the adapter can
    #: verify nobody and refuses every caller: ``google.oauth2.id_token.verify_token`` documents
    #: ``audience=None`` as "the audience is not verified", which would accept ANY Google-signed
    #: OIDC token from any project or app and read its ``email`` as a verified principal.
    iap_audience: str = ""
    #: Tenant partition asserted on outbound reviews when the principal carries none.
    tenant: str = ""
    #: GCP project the managed tracer exports to, and the one Cloud Logging names in
    #: a trace resource path. Empty is valid: on Cloud Run the exporter resolves it
    #: from the metadata server.
    project_id: str = ""
    #: Was :attr:`profile` chosen DELIBERATELY, or merely inherited because nobody set the
    #: variable? Only :meth:`load` can set this False; direct construction names the profile in
    #: code and is deliberate by definition. The seeded-persona identity adapter refuses to
    #: serve when it is False: a service whose profile variable went missing from the
    #: environment must not start handing out an approver persona.
    profile_explicit: bool = True
    adapters: Mapping[str, Mapping[str, str]] = field(
        default_factory=lambda: {port: dict(t) for port, t in DEFAULT_BINDINGS.items()}
    )

    def __post_init__(self) -> None:
        if self.profile not in KNOWN_PROFILES:
            raise ValueError(
                f"profile {self.profile!r} is not a known profile. "
                f"Use one of {', '.join(KNOWN_PROFILES)} (exact case)."
            )

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        data = _read_settings_file(path)
        choice = resolve_profile()
        return cls(
            profile=choice.profile,
            profile_explicit=choice.explicit,
            region=str(data.get("region") or _REGION),
            audit_path=str(data.get("audit_path") or ":memory:"),
            audit_anchor_path=str(data.get("audit_anchor_path") or ""),
            review_url=str(data.get("review_url") or ""),
            iap_audience=str(data.get("iap_audience") or ""),
            tenant=str(data.get("tenant") or ""),
            project_id=str(data.get("project_id") or ""),
            adapters=_bindings_from(data),
        )


class Container:
    """Lazy DI container: one ``cached_property`` per port, bound by the active profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port: str) -> object:
        table = self.settings.adapters[port]
        target = table[self.settings.profile]
        module_path, _, cls_name = target.partition(":")
        adapter_cls = getattr(importlib.import_module(module_path), cls_name)
        return adapter_cls(self.settings)

    @cached_property
    def audit(self) -> AuditSinkPort:
        adapter = self._bind("audit")
        assert isinstance(adapter, AuditSinkPort)
        return adapter

    @cached_property
    def identity(self) -> IdentityPort:
        adapter = self._bind("identity")
        assert isinstance(adapter, IdentityPort)
        return adapter

    @cached_property
    def review_router(self) -> ReviewRouterPort:
        adapter = self._bind("review_router")
        assert isinstance(adapter, ReviewRouterPort)
        return adapter

    @cached_property
    def tracer(self) -> ObservabilityTracerPort:
        adapter = self._bind("tracer")
        assert isinstance(adapter, ObservabilityTracerPort)
        return adapter

    @cached_property
    def evaluation(self) -> EvaluationGatePort:
        adapter = self._bind("evaluation")
        assert isinstance(adapter, EvaluationGatePort)
        return adapter

    @cached_property
    def generation(self) -> GenerationPort:
        adapter = self._bind("generation")
        assert isinstance(adapter, GenerationPort)
        return adapter

    @cached_property
    def extraction(self) -> ExtractionPort:
        adapter = self._bind("extraction")
        assert isinstance(adapter, ExtractionPort)
        return adapter


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.load())


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the same ``adapters:`` table the container binds from, so a deployment that rebound
    the identity port in ``config/settings.yaml`` (the documented on-premises path: swap the
    placeholder for the client's own IdP adapter) is answered about the adapter it ACTUALLY
    runs, not about the one the profile name suggests.

    Constructing is deliberately avoided: the seeded-persona adapter refuses to construct under
    an inherited profile, so a posture computed from an instance would be unobtainable in one
    of the exact cases it has to describe.
    """
    target = settings.adapters["identity"][settings.profile]
    module_path, _, class_name = target.partition(":")
    resolved = getattr(importlib.import_module(module_path), class_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {target!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See ``ports/identity.py``: neither the profile string nor the presence of a
    service-to-service secret can answer it.

    Any failure to establish the answer resolves to ``CLIENT_ASSERTED``. A guard that switches
    OFF because a lookup raised is a guard that fails open, and nothing is lost by failing
    closed here: the same failure surfaces loudly at the first request, when the container
    resolves the identical binding for real.
    """
    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:
        return CLIENT_ASSERTED
