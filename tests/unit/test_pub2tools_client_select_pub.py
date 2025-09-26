import os
import tempfile
from datetime import datetime, timedelta, UTC
from pathlib import Path
import pytest
from biotoolsllmannotate.ingest import pub2tools_client


def test_fetch_via_cli_select_pub(monkeypatch):
    # Simulate PUB2TOOLS_CLI as a dummy echo command for safe testing
    monkeypatch.setenv("PUB2TOOLS_CLI", "echo")
    since = datetime.now(UTC) - timedelta(days=7)
    # Should call echo with correct args, not actually run pub2tools
    result = pub2tools_client.fetch_via_cli(since)
    # Since echo returns no JSON, result should be []
    assert result == []

    # Check command construction for new pipeline
    cli = "echo"
    cli_parts = [cli]
    from_date = since.isoformat()[:10]
    to_date = datetime.now(UTC).isoformat()[:10]
    output_dir = "out/pub2tools"
    expected_cmd = cli_parts + [
        "-select-pub",
        output_dir,
        "--from",
        from_date,
        "--to",
        to_date,
    ]
    called = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd

        class Result:
            stdout = "[]"

        return Result()

    monkeypatch.setattr(pub2tools_client.subprocess, "run", fake_run)
    pub2tools_client.fetch_via_cli(since)
    assert called["cmd"] == expected_cmd
