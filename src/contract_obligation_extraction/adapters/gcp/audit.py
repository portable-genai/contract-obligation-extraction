"""GCP AuditSinkPort: Cloud Logging locked WORM bucket (SDK imports stay lazy)."""

from __future__ import annotations

from hex_service_kit.serialization import to_jsonable

from ...config import Settings
from ...domain.kernel import AuditEvent


class CloudAuditAdapter:
    """Write already-redacted audit events to a Cloud Logging WORM sink.

    The ``google-cloud-logging`` import lives inside the method so the ``local``/``onprem``
    profiles import this module with no GCP SDK installed (the portability proof).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def record(self, event: AuditEvent) -> None:  # pragma: no cover - needs live GCP
        # Lazy import: absent in the offline profile and in CI (hence import-not-found ignore).
        from google.cloud import logging as cloud_logging

        client = cloud_logging.Client()
        logger = client.logger("contract_obligation_extraction-audit")
        logger.log_struct(to_jsonable(event), severity="NOTICE")
