"""Tool functions an agent runtime calls: thin, side-effect-honest wrappers on the services.

Design rules, in the order they matter:

* **No business logic here.** The domain service decides HOW; the model only decides WHICH tool
  to call. A rule that lives in a tool wrapper is a rule the CLI and the API do not have.
* **Rule R8 applies on this path too.** An escalated result is ROUTED from inside the tool, in
  the same call that produced it. An agent surface that only returned the flag would be a third
  place an escalation can quietly stop, after the API and the CLI.
* **Import-safe without a runtime.** ``google.adk`` is imported lazily inside
  :func:`build_function_tools`, so these callables are importable, testable and runnable with
  no ADK and no cloud SDK installed.
* **Typed and documented.** A runtime derives each tool's name, description and JSON parameter
  schema from the signature and the docstring, so both are part of the contract.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from hex_service_kit.serialization import to_jsonable
from pii_kit import redact

from ..config import Container, Settings, build_container
from ..domain.corpus import AS_OF, contract_by_id
from ..domain.models import TriageInput
from ..domain.pii import PII_PATTERNS
from ..domain.triage_service import TriageService
from ..flow import run_contract_register

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

#: The identity a tool call is attributed to when the runtime propagates none. It names the
#: SERVICE, not a person, so an unattributed action is never mistaken for a human's.
DEFAULT_ACTOR = "contract-obligation-extraction-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _redacted(node: Any) -> Any:
    """Mask personal data in every string of a tool result, however deeply it is nested.

    A tool result is not an API response. The API returns to the authenticated caller the text
    that caller just submitted; a TOOL result goes into a model's context, and P-04 says
    minimise the data that reaches a model. The evidence snippet a caller may legitimately read
    back is therefore masked here, on the way to the agent, using the same pattern pack the
    audit write masks with. Walking the whole structure rather than three named fields means a
    future field cannot arrive unredacted just because nobody remembered to add it.
    """
    if isinstance(node, str):
        return redact(node, PII_PATTERNS)
    if isinstance(node, dict):
        return {key: _redacted(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_redacted(value) for value in node]
    return node


def triage_case(
    subject: str,
    text: str,
    actor: str = DEFAULT_ACTOR,
    tenant: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Triage one case and route it for human review when it escalates.

    Scores the case into a deterministic severity band, writes an already-redacted audit event,
    and, when the band escalates, submits the result to the human-review console (rule R8).

    Args:
      subject: The party or case the description is about.
      text: The free-text case description.
      actor: The verified identity this call is attributed to.
      tenant: Tenant partition asserted on an outbound review.

    Returns:
      A JSON-safe result dict with every string masked for personal data (P-04: a tool result
      goes into a model's context), plus ``review_ref``: where the escalation WENT. It is empty
      only when the result did not escalate, so a caller can tell a routed escalation from a
      flag nobody read.
    """
    container = _container(settings)
    case = TriageInput(subject=subject, text=text)
    result = TriageService(container.audit, container.tracer).triage(case, actor=actor)
    review_ref = ""
    if result.requires_human_review:
        review_ref = container.review_router.route(result, maker=actor, tenant=tenant)
    payload = _redacted(to_jsonable(result))
    if not isinstance(payload, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("a triage result must serialise to a JSON object")
    # Attached after the redaction pass: it is a routing reference, not narrative text, and
    # masking an identifier would break the caller's ability to look the review up.
    payload["review_ref"] = review_ref
    return payload


def extract_contract_register(
    contract_id: str,
    as_of: str = "",
    actor: str = DEFAULT_ACTOR,
    tenant: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Read a corpus contract into its obligation register and route it for review if consequential.

    Segments the contract, asks the bound extractor to PROPOSE obligations, dates and risk flags,
    admits them through the deterministic engine (dropping candidates that cite an unreal clause,
    validating flags against the taxonomy, computing deadline status), narrates the result, and,
    when the register carries any material finding, submits it to the human-review console (R8).

    Args:
      contract_id: A seed contract id (the corpus stands in for uploaded documents offline).
      as_of: Reference date (YYYY-MM-DD) for the renewal clock; empty uses the corpus date.
      actor: The verified identity this call is attributed to.
      tenant: Tenant partition asserted on an outbound review.

    Returns:
      A JSON-safe register with every string masked for personal data (P-04: a tool result goes
      into a model's context), plus ``review_ref``: where the escalation WENT, empty only when the
      register did not escalate. The versioned Rgc8 feed envelope is included under ``feed``.
    """
    contract = contract_by_id(contract_id)
    if contract is None:
        return {"error": f"no contract {contract_id!r} in the corpus"}
    resolved_as_of = date.fromisoformat(as_of) if as_of else AS_OF
    outcome = run_contract_register(
        _container(settings), contract, as_of=resolved_as_of, actor=actor, tenant=tenant
    )
    reg = outcome.register
    payload: dict[str, Any] = {
        "contract_id": reg.contract_id,
        "family": reg.family.value,
        "counterparty": reg.counterparty,
        "severity": reg.severity.value,
        "decision": reg.decision.value,
        "requires_human_review": reg.requires_human_review,
        "obligations": [
            {
                "clause_anchor": row.clause_anchor,
                "text": row.text,
                "owner": row.owner,
                "flags": list(row.flag_values),
                "needs_review": row.needs_review,
            }
            for row in reg.obligations
        ],
        "dropped": list(reg.dropped),
        "summary": outcome.note.text,
        "feed": to_jsonable(reg.snapshot),
    }
    masked = _redacted(payload)
    if not isinstance(masked, dict):  # pragma: no cover - dicts stay dicts through redaction
        raise TypeError("a register must serialise to a JSON object")
    # Attached after redaction: a routing reference is not narrative text, and masking it would
    # break the caller's ability to look the review up.
    masked["review_ref"] = outcome.review_ref
    return masked


def verify_audit_trail(settings: Settings | None = None) -> dict[str, Any]:
    """Verify the audit trail's hash chain and its external head anchor.

    Returns:
      A dict with ``ok``, the record counts and a ``detail`` string. ``ok`` is false for an
      edited, deleted or reordered record, and, when an external anchor is configured, for a
      truncated tail as well. Without an anchor a truncation cannot be detected, and the detail
      says so rather than implying a stronger guarantee than the store provides.
    """
    resolved = settings or Settings.load()
    audit = _container(resolved).audit
    verify = getattr(audit, "verify", None)
    if verify is None:
        raise NotImplementedError(
            f"the {resolved.profile} audit adapter does not expose chain verification; a "
            "managed WORM sink is verified by its own retention policy, not from here"
        )
    report = verify()
    return {
        "ok": report.ok,
        "entries": report.entries,
        "chained": report.chained,
        "legacy": report.legacy,
        "first_bad_seq": report.first_bad_seq,
        "detail": report.detail,
        "anchored": bool(resolved.audit_anchor_path),
    }


#: The tool table. The agent card advertises exactly these, by function name.
TOOL_FUNCTIONS = (triage_case, extract_contract_register, verify_audit_trail)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each callable as a runtime FunctionTool (the only ADK-dependent code path).

    The import is deliberately here rather than at module scope: without it this module, the
    card and every tool would need an agent runtime installed to be imported at all, and the
    offline gate installs none.
    """
    # No ignore comment: the missing-import error for this module is already reported (and
    # ignored) at the TYPE_CHECKING import above, and a second one would be flagged as unused.
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=function) for function in TOOL_FUNCTIONS]
