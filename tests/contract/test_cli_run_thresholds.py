import json
import os
import subprocess
import sys
from pathlib import Path


def test_min_score_filtering_affects_inclusion(tmp_path):
    """Higher --min-score should include fewer tools in payload.

    Contract assumptions:
    - CLI reads input from `BIOTOOLS_ANNOTATE_INPUT` when set.
    - Report contains per-line JSON objects; payload is a JSON array.
    - With `--min-score 0.99`, payload is often empty on sample data.
    """
    fixture = tmp_path / "sample_pub2tools.json"
    # Provide a simple candidate list; implementation will assess and filter
    fixture.write_text(
        json.dumps(
            [
                {"id": "t1", "title": "FooTool", "urls": ["https://example.org"]},
                {"id": "t2", "title": "BarTool", "urls": ["https://example.com"]},
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(repo_root / "src")
    env["BIOTOOLS_ANNOTATE_INPUT"] = str(fixture)

    payload_lo = tmp_path / "payload_lo.json"
    report_lo = tmp_path / "report_lo.jsonl"
    proc_lo = subprocess.run(
            [
                sys.executable,
                "-m",
                "biotoolsllmannotate",
                "--since",
                "7d",
                "--min-score",
                "0.1",
                "--offline",
                "--output",
                str(payload_lo),
                "--report",
                str(report_lo),
            ],
        env=env,
        capture_output=True,
        text=True,
    )

    payload_hi = tmp_path / "payload_hi.json"
    report_hi = tmp_path / "report_hi.jsonl"
    proc_hi = subprocess.run(
            [
                sys.executable,
                "-m",
                "biotoolsllmannotate",
                "--since",
                "7d",
                "--min-score",
                "0.99",
                "--offline",
                "--output",
                str(payload_hi),
                "--report",
                str(report_hi),
            ],
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc_lo.returncode == 0
    assert proc_hi.returncode == 0

    lo = json.loads(payload_lo.read_text(encoding="utf-8"))
    hi = json.loads(payload_hi.read_text(encoding="utf-8"))
    assert isinstance(lo, list) and isinstance(hi, list)
    assert len(hi) <= len(lo)
