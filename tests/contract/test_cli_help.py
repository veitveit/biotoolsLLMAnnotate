import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_module_help_shows_usage():
    """`python -m biotoolsllmannotate --help` prints usage and exits 0."""
    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(repo_root / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "biotoolsllmannotate", "--help"],
        capture_output=True,
        env=env,
        text=True,
    )
    # Expect a successful exit and standard help markers once implemented
    assert proc.returncode == 0
    out = proc.stdout.lower()
    assert ("usage" in out) or ("options" in out)


def test_console_script_help_if_available():
    """If `biotools-annotate` is on PATH, `--help` prints usage and exits 0."""
    exe = shutil.which("biotools-annotate")
    if not exe:
        # Console script may not exist until package is installed.
        # This is an optional contract check for distribution packaging.
        return
    proc = subprocess.run([exe, "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    out = proc.stdout.lower()
    assert ("usage" in out) or ("options" in out)
