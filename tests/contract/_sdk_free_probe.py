"""Construct every adapter of one profile in a FRESH interpreter with the cloud SDKs blocked.

Run as ``python -m tests.contract._sdk_free_probe <profile>``; exits 0 when every port of that
profile imported and constructed, non-zero with the offending module otherwise.

Why a subprocess rather than a fixture that reloads modules in place: reloading rebinds the
adapter classes, so every already-imported test module would keep a stale class object and
``isinstance`` checks elsewhere in the suite would start failing for reasons that have nothing
to do with the code under test. A fresh process proves the stronger claim anyway (a whole
interpreter that never had the SDK available) and leaves the running suite untouched.
"""

from __future__ import annotations

import importlib
import sys

BLOCKED_ROOTS = ("google",)


class _BlockedSdkFinder:
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> None:
        if any(fullname == r or fullname.startswith(r + ".") for r in BLOCKED_ROOTS):
            raise ModuleNotFoundError(f"{fullname} is blocked: this profile must need no SDK")
        return None


def main(profile: str) -> int:
    for name in [n for n in sys.modules if any(n.startswith(r) for r in BLOCKED_ROOTS)]:
        del sys.modules[name]
    sys.meta_path.insert(0, _BlockedSdkFinder())  # type: ignore[arg-type]

    from contract_obligation_extraction.config import DEFAULT_BINDINGS, Settings
    from contract_obligation_extraction.ports import PORT_PROTOCOLS

    settings = Settings(profile=profile, audit_path=":memory:")
    for port, protocol in PORT_PROTOCOLS.items():
        target = DEFAULT_BINDINGS[port][profile]
        module_path, _, class_name = target.partition(":")
        adapter = getattr(importlib.import_module(module_path), class_name)(settings)
        if not isinstance(adapter, protocol):
            print(f"{target} does not satisfy {protocol.__name__}", file=sys.stderr)
            return 1
    print(f"{profile}: every port constructed with no cloud SDK importable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
