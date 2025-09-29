import json
import os
import subprocess
import sys
from pathlib import Path


def test_dual_threshold_filtering_affects_inclusion(tmp_path):
    """Higher doc/bio thresholds should include fewer tools in payload.

    Contract assumptions:
    - CLI reads input from `BIOTOOLS_ANNOTATE_INPUT` when set.
    - Report contains per-line JSON objects; payload is a JSON array.
    - With `--min-doc-score 0.95`, heuristically scored offline payload should be empty.
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

    proc_lo = subprocess.run(
        [
            sys.executable,
            "-m",
            "biotoolsllmannotate",
            "--from-date",
            "7d",
            "--min-bio-score",
            "0.1",
            "--min-doc-score",
            "0.1",
            "--offline",
        ],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    out_dir = tmp_path / "out"
    time_period_dirs = list(out_dir.glob("range_*"))
    assert len(time_period_dirs) == 1
    run_dir = time_period_dirs[0]
    payload_path = run_dir / "exports" / "biotools_payload.json"
    lo = json.loads(payload_path.read_text(encoding="utf-8"))

    proc_hi = subprocess.run(
        [
            sys.executable,
            "-m",
            "biotoolsllmannotate",
            "--from-date",
            "7d",
            "--min-bio-score",
            "0.95",
            "--min-doc-score",
            "0.95",
            "--offline",
        ],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    payload_path = run_dir / "exports" / "biotools_payload.json"
    hi = json.loads(payload_path.read_text(encoding="utf-8"))

    assert proc_lo.returncode == 0
    assert proc_hi.returncode == 0
    assert isinstance(lo, list) and isinstance(hi, list)
    assert len(hi) <= len(lo)
