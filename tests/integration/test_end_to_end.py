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

    payload = tmp_path / "payload.json"
    report = tmp_path / "report.jsonl"

    env = os.environ.copy()
    env["BIOTOOLS_ANNOTATE_INPUT"] = str(fixture)
    env["PYTHONPATH"] = str(repo_root / "src")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "biotoolsllmannotate",
            "--since",
            "7d",
            "--output",
            str(payload),
            "--report",
            str(report),
        ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0
    data = json.loads(payload.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    for obj in data:
        assert isinstance(obj.get("name"), str)
        assert isinstance(obj.get("description"), str)
