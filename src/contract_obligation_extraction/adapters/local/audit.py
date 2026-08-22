"""Local AuditSinkPort: the SDK-free hash-chained WORM audit log from the commons.

The external head anchor (practices check C9) is wired here, not merely documented in the
runbook. The hash chain detects an in-place edit, an interior deletion and a reorder, but it
CANNOT detect a truncated tail on its own: dropping the newest rows leaves a shorter chain that
verifies perfectly. ``audit_anchor_path`` is the witness that closes that gap, and because it is
passed from ``Settings`` an operator configures it rather than patching code.
"""

from __future__ import annotations

from hex_service_kit.audit import ChainReport, HashChainedAuditLog

from ...config import Settings
from ...domain.kernel import AuditEvent


class LocalAuditAdapter:
    """Append-only, hash-chained local WORM stand-in (delegates to hex-service-kit)."""

    def __init__(self, settings: Settings) -> None:
        # Keep the anchor on a different volume from the store: a process that can rewrite the
        # SQLite file must not be able to silently rewrite the anchored head with it.
        self._log = HashChainedAuditLog(settings.audit_path, anchor_path=settings.audit_anchor_path)

    def record(self, event: AuditEvent) -> None:
        self._log.record(event)

    def verify(self) -> ChainReport:
        """Verify the chain AND cross-check the external anchor, when one is configured.

        The report is ``ok=False`` for a truncated tail only when an anchor is configured; with
        no anchor the shorter chain is indistinguishable from a shorter history, which is the
        honest limit the kit documents and the runbook repeats.
        """
        return self._log.verify_chain()

    @property
    def log(self) -> HashChainedAuditLog:
        """Expose the underlying log for verify/export in the CLI and tests."""
        return self._log
