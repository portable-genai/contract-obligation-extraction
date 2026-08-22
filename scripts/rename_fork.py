"""Rebrand this base repo for your institution / vertical in one pass.

Rewrites the python package name, the env-var prefix, the baked-in cloud resource stem and the
distribution / git id across the tree, so a fork does not have to hunt them down by hand. It is
a mechanical text plus directory rename, deliberately conservative: it prints a plan, writes
nothing unless ``--yes``, and by default leaves docs prose alone (pass ``--include-docs`` to
sweep Markdown too).

    # See what would change (no writes):
    python scripts/rename_fork.py --package acme_contract_intel --env-prefix ACME \
        --resource acme-contracts --dry-run

    # Apply it:
    python scripts/rename_fork.py --package acme_contract_intel --env-prefix ACME \
        --resource acme-contracts --yes

Two notes specific to this repo:

* **The console script is named after the package.** The ``[project.scripts]`` entry in
  ``pyproject.toml`` is keyed on the package name, so there is no separate ``--cli`` knob:
  renaming the package renames the command.
* **The env prefix has two spellings.** The trailing-underscore form prefixes every variable,
  and the bare token is carried as ``render_env_prefix`` in
  ``infra/terraform/render.tf.json``, so the Terraform stack sets the same variable names on
  the Cloud Run service. Both are rewritten.

The catalog id (``Rgc12``) is left alone unless ``--catalog-id`` is given: it names the entry in
the upstream catalog that this fork descends from, and a fork that keeps it stays traceable.
Change it when the fork publishes its own agent card to its own registry.

After running: recreate the venv and ``pip install -e ".[dev]"`` (the distribution name
changed), then run the gate. See docs/ADOPTING.md for the checklist of human decisions (rule
packs, region, IdP, eval golden set) that this script does NOT do for you.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Everything this repo was rendered with. Each one is a real string in the tree today; the
# rename is only ever a replacement of these, never a guess at a pattern.
_OLD_PACKAGE = "contract_obligation_extraction"
_OLD_ENV_PREFIX = "CONTRACT_"
_OLD_BARE_PREFIX = "CONTRACT"
_OLD_RESOURCE = "rgc12-svc"
_OLD_DIST = "contract-obligation-extraction"
_OLD_CATALOG_ID = "Rgc12"

# Directories never touched.
_SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".next",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
    "out",
    "dist",
    "build",
}
# File suffixes considered text (everything else is skipped).
_TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
    ".json",
    ".cfg",
    ".ini",
    ".txt",
    ".tf",
    ".hcl",
    ".mjs",
    ".ts",
    ".tsx",
    ".lock",
    ".env",
    ".example",
    "",
}
# Docs prose is only swept with --include-docs (keep code deterministic by default).
_DOC_SUFFIXES = {".md"}


#: This file. It is skipped, because a rename that rewrote the renamer would leave a tool whose
#: ``_OLD_*`` constants no longer name anything in the tree: half of them get replaced (the
#: package literal) and half do not (the env prefix, which is matched by a regex that a quoted
#: constant does not satisfy), so a second run would be silently wrong rather than a no-op.
_SELF = Path(__file__).resolve()


def _iter_files(include_docs: bool):
    for path in _ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.resolve() == _SELF:
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(_ROOT).parts):
            continue
        if path.suffix not in _TEXT_SUFFIXES:
            continue
        if not include_docs and path.suffix in _DOC_SUFFIXES:
            continue
        yield path


def _rewrite_text(text: str, args: argparse.Namespace) -> tuple[str, int]:
    """Apply every rename to ``text``; return the new text and the number of replacements.

    Order matters. The distribution id is the longest and most specific string, so it goes
    first; the resource stem and the package name share no substring with it (one is
    hyphenated, the other is not), but replacing the longest first keeps that independence
    from being an accident.
    """
    count = 0
    env_prefix = args.env_prefix.rstrip("_").upper()

    plain: list[tuple[str, str]] = [
        (_OLD_DIST, args.dist or args.resource),
        (_OLD_RESOURCE, args.resource),
        (_OLD_PACKAGE, args.package),
    ]
    if args.catalog_id:
        plain.append((_OLD_CATALOG_ID, args.catalog_id))
    for old, new in plain:
        count += text.count(old)
        text = text.replace(old, new)

    # The env prefix, only where it PREFIXES an upper token (CONTRACT_PROFILE), never mid-word.
    text, changed = re.subn(rf"\b{re.escape(_OLD_ENV_PREFIX)}(?=[A-Z0-9])", env_prefix + "_", text)
    count += changed

    # The bare token, only as the Terraform render constant. A blanket word-boundary rewrite of
    # a short uppercase token is how prose gets mangled, so this is pinned to the one line that
    # carries it.
    text, changed = re.subn(
        rf'("render_env_prefix"\s*:\s*)"{re.escape(_OLD_BARE_PREFIX)}"',
        rf'\g<1>"{env_prefix}"',
        text,
    )
    count += changed
    return text, count


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebrand the base repo for a fork.")
    ap.add_argument("--package", required=True, help="new python package name (snake_case)")
    ap.add_argument("--env-prefix", required=True, help="new env-var prefix, e.g. ACME")
    ap.add_argument(
        "--resource",
        required=True,
        help="new cloud resource stem (Terraform name_prefix), e.g. acme-contracts",
    )
    ap.add_argument("--dist", default="", help="new distribution / git id (default: --resource)")
    ap.add_argument(
        "--catalog-id",
        default="",
        help=f"new catalog id (default: keep {_OLD_CATALOG_ID}, so the fork stays traceable)",
    )
    ap.add_argument("--include-docs", action="store_true", help="also rewrite Markdown prose")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    ap.add_argument("--yes", action="store_true", help="apply without the confirmation prompt")
    args = ap.parse_args()

    if not re.fullmatch(r"[a-z_][a-z0-9_]*", args.package):
        ap.error("--package must be a valid snake_case python identifier")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,18}", args.resource):
        ap.error(
            "--resource must match ^[a-z][a-z0-9-]{2,18}$: it becomes the Terraform "
            "name_prefix, whose own validation in infra/terraform/variables.tf refuses "
            "anything else"
        )
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", args.env_prefix.rstrip("_")):
        ap.error("--env-prefix must be a letter followed by letters, digits or underscores")

    # Write only when explicitly applying (--yes and not --dry-run); otherwise preview.
    apply = args.yes and not args.dry_run

    print("Planned replacements (whole-tree):")
    print(f"  {_OLD_DIST!r:34} -> {(args.dist or args.resource)!r}   (distribution / git id)")
    print(f"  {_OLD_RESOURCE!r:34} -> {args.resource!r}   (Terraform name_prefix)")
    print(f"  {_OLD_PACKAGE!r:34} -> {args.package!r}   (package and console script)")
    print(
        f"  {_OLD_ENV_PREFIX!r:34} -> {args.env_prefix.rstrip('_').upper() + '_'!r}   (env prefix)"
    )
    if args.catalog_id:
        print(f"  {_OLD_CATALOG_ID!r:34} -> {args.catalog_id!r}   (catalog id)")
    else:
        print(f"  {_OLD_CATALOG_ID!r:34} -> unchanged (pass --catalog-id to rewrite it)")
    print()

    touched: list[tuple[Path, int]] = []
    for path in _iter_files(args.include_docs):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new_text, changed = _rewrite_text(text, args)
        if changed:
            touched.append((path, changed))
            if apply:
                path.write_text(new_text, encoding="utf-8")

    total = sum(changed for _, changed in touched)
    verb = "Edited" if apply else "Would edit"
    print(f"{verb} {len(touched)} file(s), {total} replacement(s).")

    # Rename the package directory last (after content is rewritten).
    pkg_dir = _ROOT / "src" / _OLD_PACKAGE
    new_pkg_dir = _ROOT / "src" / args.package
    if pkg_dir.exists() and pkg_dir != new_pkg_dir:
        print(f"{'Renaming' if apply else 'Would rename'} {pkg_dir} -> {new_pkg_dir}")
        if apply:
            pkg_dir.rename(new_pkg_dir)

    if not apply:
        print("\nNo files were written. Re-run with --yes to apply (or --dry-run to preview).")
        return 0
    print('\nDone. Next: recreate the venv, `pip install -e ".[dev]"`, and run `make gate`.')
    print("Then finish the human steps in docs/ADOPTING.md (rule packs, region, IdP, eval).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
