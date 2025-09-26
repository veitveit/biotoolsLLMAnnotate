from __future__ import annotations


def run_all_month(
    out_dir: Path,
    month: str,
    edam_owl: str = "http://edamontology.org/EDAM.owl",
    idf: str = "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
    idf_stemmed: str = "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
    selenium: bool = False,
    firefox_path: str | None = None,
    java_opts: list[str] | None = None,
    extra_args: list[str] | None = None,
    cli_path: str | None = None,
    custom_restriction: str | None = "SRC:MED OR SRC:PMC",
    disable_tool_restriction: bool = True,
    timeout: int = 6000,
    retryLimit: int = 0,
    fetcher_threads: int = 4,
) -> Path | None:
    """Run Pub2Tools -all for a given month, writing outputs to out_dir.

    Returns the path to `to_biotools.json` if the run appears successful.
    """
    cli = _find_cli(cli_path)
    if not cli:
        print(
            "ERROR: Pub2Tools CLI not found. Please install pub2tools or set PUB2TOOLS_CLI."
        )
        return None
    import shlex

    cli_parts = shlex.split(cli)
    cmd = []
    # If cli is a java -jar command, prepend java opts
    if cli_parts[0] == "java":
        java_opts = java_opts or ["-Xms2048M", "-Xmx4096M"]
        cmd += ["java"] + java_opts + cli_parts[1:]
    else:
        cmd += cli_parts
    cmd += [
        "-all",
        str(out_dir),
        "--edam",
        edam_owl,
        "--idf",
        idf,
        "--idf-stemmed",
        idf_stemmed,
        "--month",
        month,
    ]
    if custom_restriction:
        cmd += ["--custom-restriction", custom_restriction]
    if disable_tool_restriction:
        cmd += ["--disable-tool-restriction"]

    cmd += [
        "--timeout",
        str(timeout),
        "--retryLimit",
        str(retryLimit),
        "--fetcher-threads",
        str(fetcher_threads),
    ]
    if selenium:
        cmd += ["--seleniumFirefox"]
        if firefox_path:
            cmd += [firefox_path]
    if extra_args:
        cmd += extra_args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Check for expected output file
        out_json = out_dir / "to_biotools.json"
        if out_json.exists():
            return out_json
        print(
            f"WARNING: Pub2Tools ran but did not produce to_biotools.json.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        return None
    except subprocess.CalledProcessError as cpe:
        print(
            f"ERROR: Pub2Tools -all failed.\nCommand: {' '.join(cmd)}\nExit code: {cpe.returncode}\nSTDOUT:\n{cpe.stdout}\nSTDERR:\n{cpe.stderr}"
        )
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error running Pub2Tools -all: {e}")
        return None


"""Integration helpers for Pub2Tools.

This module attempts to fetch newly discovered tool candidates from Pub2Tools.
It supports two strategies:

1) Local JSON export path (explicit) — pass a path to a JSON array produced by
   Pub2Tools. This is the most reproducible option for CI/tests.
2) External CLI invocation — if a `pub2tools` CLI is available (or path is set
   via `PUB2TOOLS_CLI`), call it to retrieve recent candidates as JSON.

Network/API integration can be added later if required. This design keeps the
ingestion pluggable and testable without network IO.
"""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _iso_utc(dt: datetime) -> str:
    dt = dt.astimezone(UTC)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Pub2Tools may emit a bare array or wrap it inside an object with a
        # "list" key; support both shapes to stay compatible with CLI outputs.
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            candidates = data.get("list") if isinstance(data.get("list"), list) else []
        else:
            candidates = []
        return [x for x in candidates if isinstance(x, dict)]
    except Exception:
        return []


def fetch_from_export(path: Path) -> list[dict[str, Any]]:
    """Load candidates from a Pub2Tools JSON export file."""
    return _load_json_array(path)


def _find_cli(cli_path: str | None = None) -> str | None:
    # If explicit path provided, use it
    if cli_path:
        # Check if it's a file path that exists and is executable
        cli_file_path = Path(cli_path)
        if cli_file_path.exists() and os.access(cli_path, os.X_OK):
            return cli_path
        # If it's not a file path, treat it as a command string (e.g., "java -jar ...")
        # We'll validate it when we try to run it
        return cli_path

    # Prefer explicit env var
    cli = os.environ.get("PUB2TOOLS_CLI")
    if cli:
        return cli

    # Check config file for p2t_cli setting
    try:
        # Try to load config directly
        import yaml

        config_path = Path(__file__).resolve().parents[3] / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
            config_cli = config.get("pub2tools", {}).get("p2t_cli")
            if config_cli:
                return config_cli
    except Exception:
        # If config loading fails, continue with other methods
        pass

    # Fallback: look for `pub2tools` on PATH
    found = shutil.which("pub2tools")
    if found:
        return found
    # Check tools/pub2tools/ for a local install
    repo_root = Path(__file__).resolve().parents[3]
    local_cli = repo_root / "tools" / "pub2tools" / "pub2tools"
    if local_cli.exists() and os.access(local_cli, os.X_OK):
        return str(local_cli)
    return None


def fetch_via_cli(
    since: datetime,
    to_date: datetime | None = None,
    *,
    limit: int | None = None,
    cli_path: str | None = None,
    edam_owl: str = "http://edamontology.org/EDAM.owl",
    idf: str = "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
    idf_stemmed: str = "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
) -> list[dict[str, Any]]:
    """Invoke a Pub2Tools CLI to fetch recent candidates as JSON.

    This uses the -all command with --from and --to to run the full pipeline.

    If no CLI is found or the invocation fails, returns an empty list.
    """
    from ..config import get_config_yaml

    config = get_config_yaml()
    timeout = config.get("pub2tools", {}).get("timeout", 6000)
    retryLimit = config.get("pub2tools", {}).get("retryLimit", 0)
    fetcher_threads = config.get("pub2tools", {}).get("fetcher_threads", 4)

    cli = _find_cli(cli_path)
    if not cli:
        print(
            "ERROR: Pub2Tools CLI not found. Please install pub2tools or set PUB2TOOLS_CLI. Candidates cannot be fetched."
        )
        return []
    import shlex

    cli_parts = shlex.split(cli)
    from_date = _iso_utc(since)[:10]  # YYYY-MM-DD
    to_date_str = (
        _iso_utc(to_date)[:10] if to_date else _iso_utc(datetime.now(UTC))[:10]
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"out/pub2tools_{timestamp}"
    cmd = cli_parts + [
        "-all",
        output_dir,
        "--from",
        from_date,
        "--to",
        to_date_str,
        "--edam",
        edam_owl,
        "--idf",
        idf,
        "--idf-stemmed",
        idf_stemmed,
        "--timeout",
        str(timeout),
        "--retryLimit",
        str(retryLimit),
        "--fetcher-threads",
        str(fetcher_threads),
    ]
    print(f"Running Pub2Tools command: {' '.join(cmd)}")
    try:
        # Add timeout to prevent hanging (1 day for now, can be adjusted)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=86400,  # 1 day timeout
        )
        # Load the to_biotools.json file
        to_biotools_path = Path(output_dir) / "to_biotools.json"
        if to_biotools_path.exists():
            return _load_json_array(to_biotools_path)
        else:
            print(
                f"ERROR: Pub2Tools -all ran but did not produce to_biotools.json.\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
            return []
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: Pub2Tools command timed out after 1 day.\nCommand: {' '.join(cmd)}"
        )
        return []
    except subprocess.CalledProcessError as cpe:
        print(
            f"ERROR: Pub2Tools CLI was found but failed to run.\nCommand: {' '.join(cmd)}\nExit code: {cpe.returncode}\nSTDOUT:\n{cpe.stdout}\nSTDERR:\n{cpe.stderr}"
        )
        return []
    except Exception as e:
        print(f"ERROR: Unexpected error running Pub2Tools CLI: {e}")
        return []


def _default_cli_path() -> str | None:
    """Try to locate the local wrapper installed under repo `bin/pub2tools`."""
    # Resolve repo root as two parents up from this file: src/.../ingest
    here = Path(__file__).resolve()
    repo_root = here.parents[3] if len(here.parents) >= 4 else here.parent
    candidate = repo_root / "bin" / "pub2tools"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def run_month_all(
    out_dir: Path,
    *,
    month: str,
    edam_owl: str = "http://edamontology.org/EDAM.owl",
    idf: str = "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
    idf_stemmed: str = "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
    selenium: bool = False,
    firefox_path: str | None = None,
    java_opts: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> Path | None:
    """Run Pub2Tools end-to-end for a given month, writing outputs to out_dir.

    Returns the path to `to_biotools.json` if the run appears successful.
    Note: This invocation downloads EDAM + IDF files from the web and may take
    hours depending on month size. Use with care in CI.
    """
    cli = _find_cli() or _default_cli_path()
    if not cli:
        return None
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [cli]
    # If `cli` points directly to `java -jar` wrapper, java opts need to be in wrapper.
    # Otherwise, if cli is a jar path, prepend java options. Our wrapper handles java.
    # So here we just pass options to Pub2Tools.
    pub2_args = [
        "-all",
        str(out_dir),
        "--edam",
        edam_owl,
        "--idf",
        idf,
        "--idf-stemmed",
        idf_stemmed,
        "--month",
        month,
    ]
    if not selenium:
        pub2_args += ["--selenium", "false"]
    if firefox_path:
        pub2_args += ["--seleniumFirefox", firefox_path]
    if extra_args:
        pub2_args += list(extra_args)

    try:
        subprocess.run(cmd + pub2_args, check=True)
    except Exception:
        return None

    tb = out_dir / "to_biotools.json"
    return tb if tb.exists() else None


def load_to_biotools_json(out_dir: Path) -> list[dict[str, Any]]:
    """Load the primary output file `to_biotools.json` from an output directory."""
    tb = out_dir / "to_biotools.json"
    return _load_json_array(tb)
