from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from biotoolsllmannotate.ingest import pub2tools_client


def test_fetch_via_cli_select_pub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure fetch_via_cli builds expected command arguments."""
    # Simulate PUB2TOOLS_CLI as a dummy echo command for safe testing
    monkeypatch.setenv("PUB2TOOLS_CLI", "echo")
    since = datetime.now(UTC) - timedelta(days=7)
    # Should call echo with correct args, not actually run pub2tools
    result = pub2tools_client.fetch_via_cli(since)
    # Since echo returns no JSON, result should be []
    assert result == []

    # Check command construction for new pipeline
    cli = "echo"
    from_date = since.isoformat()[:10]
    called: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
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
