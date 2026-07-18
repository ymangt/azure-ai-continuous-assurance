"""One-time Azure Monitor OpenTelemetry bootstrap."""

from __future__ import annotations

import os
from threading import Lock

from azure.monitor.opentelemetry import configure_azure_monitor

_CONFIGURATION_LOCK = Lock()
_CONFIGURED = False


def configure_azure_observability(connection_string: str | None = None) -> bool:
    """Configure the Azure Monitor distro once when a connection string is available."""

    global _CONFIGURED
    resolved = connection_string or os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not resolved:
        return False
    with _CONFIGURATION_LOCK:
        if _CONFIGURED:
            return True
        configure_azure_monitor(
            connection_string=resolved,
            disable_offline_storage=True,
            enable_live_metrics=False,
            logger_name="aica",
        )
        _CONFIGURED = True
    return True
