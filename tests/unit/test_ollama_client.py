from __future__ import annotations

from typing import Any

import pytest
import requests

from biotoolsllmannotate.assess.ollama_client import OllamaClient, OllamaConnectionError


def test_ollama_client_uses_retry_configuration() -> None:
    """Client honors retry configuration for adapters."""
    config = {
        "ollama": {
            "host": "http://example.invalid",
            "max_retries": 5,
            "retry_backoff_seconds": 0.5,
        },
        "logging": {},
        "pipeline": {},
    }

    client = OllamaClient(config=config)

    assert client.max_retries == 5
    assert client.retry_backoff_seconds == 0.5

    http_adapter = client.session.adapters["http://"]
    https_adapter = client.session.adapters["https://"]

    assert http_adapter.max_retries.total == 5
    assert https_adapter.max_retries.total == 5
    assert http_adapter.max_retries.backoff_factor == pytest.approx(0.5)
    assert https_adapter.max_retries.backoff_factor == pytest.approx(0.5)


def test_generate_retries_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generate retries on connection errors and raises custom error."""
    config = {
        "ollama": {
            "host": "http://example.invalid",
            "max_retries": 2,
            "retry_backoff_seconds": 0,
            "model": "dummy",
        },
        "logging": {},
        "pipeline": {},
    }

    client = OllamaClient(config=config)

    calls = 0

    def fake_post(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(client.session, "post", fake_post)

    with pytest.raises(OllamaConnectionError):
        client.generate("Tell me something")

    assert calls == 3  # initial + 2 retries
