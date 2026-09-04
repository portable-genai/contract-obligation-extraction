"""Minimal stdlib CLI: triage a case, read a contract register, or verify the chain (argparse)."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from hex_service_kit.logging import configure_logging

from ..config import build_container
from ..domain.corpus import AS_OF, contract_by_id
from ..domain.models import TriageInput
from ..domain.triage_service import TriageService
from ..flow import run_contract_register


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="contract_obligation_extraction")
    sub = parser.add_subparsers(dest="command", required=True)

    triage_cmd = sub.add_parser("triage", help="Triage a single case.")
    triage_cmd.add_argument("subject")
    triage_cmd.add_argument("text")
    triage_cmd.add_argument("--actor", default="cli-user@bank.example")
    triage_cmd.add_argument(
        "--tenant", default="", help="Tenant partition asserted to human-review-console."
    )

    reg_cmd = sub.add_parser("register", help="Read a corpus contract into its register.")
    reg_cmd.add_argument("contract_id", help="A seed contract id (see the corpus).")
    reg_cmd.add_argument("--as-of", default="", help="Reference date (YYYY-MM-DD); default corpus.")
    reg_cmd.add_argument("--actor", default="cli-user@bank.example")
    reg_cmd.add_argument(
        "--tenant", default="", help="Tenant partition asserted to human-review-console."
    )

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI configures once.
    configure_logging(container.settings.profile, service="contract-obligation-extraction")

    if args.command == "triage":
        service = TriageService(container.audit, container.tracer)
        result = service.triage(TriageInput(subject=args.subject, text=args.text), actor=args.actor)
        print(f"{result.subject}: {result.severity.value} ({result.decision.value})")
        print(f"  requires_human_review: {result.requires_human_review}")
        if result.requires_human_review:
            # Rule R8 on the CLI path too: the same escalation, the same router. A surface that
            # only printed the flag would be a second place for an escalation to stop.
            ref = container.review_router.route(result, maker=args.actor, tenant=args.tenant)
            print(f"  routed to human review: {ref}")
        return 0

    if args.command == "register":
        contract = contract_by_id(args.contract_id)
        if contract is None:
            print(f"no contract {args.contract_id!r} in the corpus", file=sys.stderr)
            return 2
        as_of = date.fromisoformat(args.as_of) if args.as_of else AS_OF
        outcome = run_contract_register(
            container, contract, as_of=as_of, actor=args.actor, tenant=args.tenant
        )
        reg = outcome.register
        print(f"{reg.subject}: {reg.severity.value} ({reg.decision.value})")
        print(f"  obligations={len(reg.obligations)} dropped={len(reg.dropped)}")
        for row in reg.obligations:
            flags = ",".join(row.flag_values) or "-"
            mark = " [needs review]" if row.needs_review else ""
            print(f"  {row.clause_anchor}: {flags}{mark}")
        print(f"  summary: {outcome.note.text}")
        if reg.requires_human_review:
            print(f"  routed to human review: {outcome.review_ref}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
