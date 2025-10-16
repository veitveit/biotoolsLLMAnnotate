import json
import os
import subprocess
import sys
from pathlib import Path


def test_end_to_end_on_fixture(tmp_path):
    """E2E: use fixture input to produce payload and report with minimal entries."""
    repo_root = Path(__file__).resolve().parents[2]
    fixture = repo_root / "tests" / "fixtures" / "pub2tools" / "sample.json"
    assert fixture.exists(), "Missing test fixture"

    env = os.environ.copy()
    env["BIOTOOLS_ANNOTATE_INPUT"] = str(fixture)
    env["PYTHONPATH"] = str(repo_root / "src")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "biotoolsllmannotate",
            "--from-date",
            "7d",
            "--input",
            str(fixture),
            "--offline",
        ],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert proc.returncode == 0
    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    payload = run_dir / "exports" / "biotools_payload.json"
    data = json.loads(payload.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    for obj in data:
        assert isinstance(obj.get("name"), str)
        assert isinstance(obj.get("description"), str)
