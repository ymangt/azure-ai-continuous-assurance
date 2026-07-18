from __future__ import annotations

import aica.observability as observability


def test_azure_monitor_bootstrap_is_optional_and_idempotent(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(observability, "_CONFIGURED", False)
    monkeypatch.setattr(
        observability,
        "configure_azure_monitor",
        lambda **kwargs: calls.append(kwargs),
    )

    assert observability.configure_azure_observability() is False
    assert observability.configure_azure_observability("InstrumentationKey=synthetic") is True
    assert observability.configure_azure_observability("InstrumentationKey=synthetic") is True
    assert calls == [
        {
            "connection_string": "InstrumentationKey=synthetic",
            "disable_offline_storage": True,
            "enable_live_metrics": False,
            "logger_name": "aica",
        }
    ]
