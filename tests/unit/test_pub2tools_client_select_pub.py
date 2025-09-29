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
    called = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd

        class Result:
            stdout = "[]"

        return Result()

    monkeypatch.setattr(pub2tools_client.subprocess, "run", fake_run)
    pub2tools_client.fetch_via_cli(since)
    cmd = called["cmd"]
    assert cmd[0] == cli
    assert cmd[1] == "-all"
    assert "--from" in cmd
    assert "--to" in cmd
    out_dir_arg = Path(cmd[2])
    assert out_dir_arg.parent == Path("out/pub2tools")
    expected_prefix = f"range_{from_date}_to_"
    assert out_dir_arg.name.startswith(expected_prefix)
    # Unique suffix appended after the range for disambiguation
    assert len(out_dir_arg.name) > len(expected_prefix)


def test_fetch_via_cli_respects_base_output(monkeypatch, tmp_path):
    monkeypatch.setenv("PUB2TOOLS_CLI", "echo")
    since = datetime.now(UTC) - timedelta(days=3)
    called = {}

    def fake_run(cmd, **kwargs):
        called["cmd"] = cmd

        class Result:
            stdout = "[]"

        return Result()

    monkeypatch.setattr(pub2tools_client.subprocess, "run", fake_run)
    base_dir = tmp_path / "pub2tools"
    # Pre-create a to_biotools.json to ensure it gets cleaned before run
    base_dir.mkdir(parents=True, exist_ok=True)
    existing_file = base_dir / "to_biotools.json"
    existing_file.write_text("old", encoding="utf-8")

    pub2tools_client.fetch_via_cli(since, base_output_dir=base_dir)
    cmd = called["cmd"]
    assert Path(cmd[2]) == base_dir
    assert not existing_file.exists()
