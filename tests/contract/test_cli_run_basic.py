import json
import os
import subprocess
import sys
from pathlib import Path


def test_run_basic_creates_outputs(tmp_path):
    """Basic run writes payload.json and report.jsonl and exits 0.

    Contract assumptions:
    - CLI reads optional env `BIOTOOLS_ANNOTATE_INPUT` to use a local fixture
      (avoids network during tests).
    - Command: `python -m biotoolsllmannotate run --from-date 7d`
    """
    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(repo_root / "src")
    env["BIOTOOLS_ANNOTATE_INPUT"] = str(tmp_path / "sample_pub2tools.json")
    # Minimal placeholder fixture; implementation should overwrite with real output
    (tmp_path / "sample_pub2tools.json").write_text("[]", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "biotoolsllmannotate",
            "--from-date",
            "7d",
            "--offline",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tmp_path),
    )

    assert proc.returncode == 0
    out_dir = tmp_path / "out"
    time_period_dirs = list(out_dir.glob("range_*"))
    assert len(time_period_dirs) == 1
    run_dir = time_period_dirs[0]
    out_payload = run_dir / "exports" / "biotools_payload.json"
    out_report = run_dir / "reports" / "assessment.jsonl"
    assert out_payload.exists()
    assert out_report.exists()
    # payload should be JSON (likely an array)
    json.loads(out_payload.read_text(encoding="utf-8"))
