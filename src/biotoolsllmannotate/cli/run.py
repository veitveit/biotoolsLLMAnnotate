from __future__ import annotations

import csv
import gzip
import json
import os
import shutil
import sys
from time import perf_counter
from collections.abc import Iterable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from biotoolsllmannotate import __version__ as PACKAGE_VERSION
from biotoolsllmannotate.io.payload_writer import PayloadWriter
from biotoolsllmannotate.schema.models import BioToolsEntry
from biotoolsllmannotate.enrich import scrape_homepage_metadata
from biotoolsllmannotate.ingest.pub2tools_fetcher import merge_edam_tags


def parse_since(value: str | None) -> datetime:
    """Parse a since value like '7d', '30d', '12h', or ISO-8601 to UTC datetime.

    Supported formats:
    - ISO-8601: '2024-01-01', '2024-01-01T00:00:00', '2024-01-01T00:00:00Z'
    - Relative: '7d', '30d', '12h', '2w', '45m', '30s'
    - Units: d=days, w=weeks, h=hours, m=minutes, s=seconds

    Returns datetime in UTC.
    """
    if not value:
        raise ValueError("Since value cannot be None or empty")

    now = datetime.now(UTC)
    v = value.strip()

    # Try ISO-8601 format first
    try:
        # Handle trailing 'Z'
        if v.endswith("Z"):
            v = v[:-1]
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        pass

    # Try relative time format
    if not v:
        raise ValueError(f"Invalid since value: '{value}'")

    # Extract number and unit
    num_part = ""
    unit_part = ""

    for i, char in enumerate(v):
        if char.isdigit():
            num_part += char
        else:
            unit_part = v[i:].lower()
            break
    else:
        # No unit found, treat as days
        unit_part = "d"

    if not num_part:
        raise ValueError(f"Invalid since value: '{value}' - no number found")

    try:
        n = int(num_part)
    except ValueError:
        raise ValueError(f"Invalid since value: '{value}' - invalid number")

    if n < 0:
        raise ValueError(
            f"Invalid since value: '{value}' - negative values not allowed"
        )

    # Parse unit
    if unit_part in {"d", "day", "days"}:
        return now - timedelta(days=n)
    elif unit_part in {"w", "week", "weeks"}:
        return now - timedelta(weeks=n)
    elif unit_part in {"h", "hour", "hours"}:
        return now - timedelta(hours=n)
    elif unit_part in {"m", "min", "mins", "minute", "minutes"}:
        return now - timedelta(minutes=n)
    elif unit_part in {"s", "sec", "secs", "second", "seconds"}:
        return now - timedelta(seconds=n)
    else:
        raise ValueError(f"Invalid since value: '{value}' - unknown unit '{unit_part}'")


def load_candidates(env_input: str | None) -> list[dict[str, Any]]:
    """Load candidates from BIOTOOLS_ANNOTATE_INPUT JSON array when provided. If not provided or file missing, return empty list."""
    if not env_input:
        return []
    p = Path(env_input)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            candidates = data.get("list") if isinstance(data.get("list"), list) else []
        else:
            candidates = []
        merged: list[dict[str, Any]] = []
        for raw in candidates:
            if isinstance(raw, dict):
                merge_edam_tags(raw)
                merged.append(raw)
        return merged
    except Exception:
        return []
    return []


def candidate_published_at(c: dict[str, Any]) -> datetime | None:
    v = c.get("published_at")
    if not v:
        return None
    try:
        s = str(v)
        if s.endswith("Z"):
            s = s[:-1]
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def normalize_url(u: str) -> str:
    u = u.strip()
    if u.startswith("//"):
        return "https:" + u
    return u


def primary_homepage(urls: Iterable[str]) -> str | None:
    for u in urls:
        nu = normalize_url(str(u))
        if nu.startswith("http://") or nu.startswith("https://"):
            return nu
    return None


def simple_scores(c: dict[str, Any]) -> dict[str, Any]:
    """A deterministic, lightweight heuristic scorer used until LLM integration.

    - Bio score: 0.8 if title/tags look bio-related, else 0.4
    - Documentation score: 0.8 if a homepage URL exists, else 0.1
    """
    title = str(c.get("title") or "").lower()
    tags = [str(t).lower() for t in (c.get("tags") or [])]
    urls = [str(u) for u in (c.get("urls") or [])]

    bio_kw = (
        ("gene" in title)
        or ("genom" in title)
        or ("bio" in title)
        or any(
            k in tags
            for k in ["genomics", "bioinformatics", "proteomics", "metabolomics"]
        )
    )
    bio = 0.8 if bio_kw else 0.4
    docs = 0.8 if primary_homepage(urls) else 0.1
    return {
        "bio_score": max(0.0, min(1.0, float(bio))),
        "documentation_score": max(0.0, min(1.0, float(docs))),
        "concise_description": (c.get("description") or "").strip()[:280],
        "rationale": "heuristic pre-LLM scoring",
    }


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def write_report_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_parent(path)
    fieldnames = [
        "id",
        "title",
        "tool_name",
        "homepage",
        "publication_ids",
        "include",
        "bio_score",
        "bio_A1",
        "bio_A2",
        "bio_A3",
        "bio_A4",
        "bio_A5",
        "documentation_score",
        "doc_B1",
        "doc_B2",
        "doc_B3",
        "doc_B4",
        "doc_B5",
        "concise_description",
        "rationale",
        "model",
        "origin_types",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            scores = row.get("scores") or {}
            bio_subscores = scores.get("bio_subscores") or {}
            doc_subscores = scores.get("documentation_subscores") or {}
            writer.writerow(
                {
                    "id": row.get("id", ""),
                    "title": row.get("title", ""),
                    "tool_name": scores.get("tool_name", ""),
                    "homepage": row.get("homepage", ""),
                    "publication_ids": ", ".join(row.get("publication_ids", []) or []),
                    "include": row.get("include", False),
                    "bio_score": scores.get("bio_score", ""),
                    "bio_A1": bio_subscores.get("A1", ""),
                    "bio_A2": bio_subscores.get("A2", ""),
                    "bio_A3": bio_subscores.get("A3", ""),
                    "bio_A4": bio_subscores.get("A4", ""),
                    "bio_A5": bio_subscores.get("A5", ""),
                    "documentation_score": scores.get("documentation_score", ""),
                    "doc_B1": doc_subscores.get("B1", ""),
                    "doc_B2": doc_subscores.get("B2", ""),
                    "doc_B3": doc_subscores.get("B3", ""),
                    "doc_B4": doc_subscores.get("B4", ""),
                    "doc_B5": doc_subscores.get("B5", ""),
                    "concise_description": scores.get("concise_description", ""),
                    "rationale": scores.get("rationale", ""),
                    "model": scores.get("model", ""),
                    "origin_types": ", ".join(scores.get("origin_types", [])),
                }
            )


def include_candidate(
    scores: dict[str, Any],
    *,
    min_bio_score: float,
    min_doc_score: float,
    has_homepage: bool,
) -> bool:
    return (
        scores.get("bio_score", 0.0) >= min_bio_score
        and scores.get("documentation_score", 0.0) >= min_doc_score
        and has_homepage
    )


def to_entry(c: dict[str, Any], homepage: str | None) -> dict[str, Any]:
    name = c.get("title") or c.get("name") or "Unnamed Tool"
    desc = c.get("description") or "Candidate tool from Pub2Tools"
    homepage = homepage or ""
    entry: dict[str, Any] = {
        "name": str(name),
        "description": str(desc),
        "homepage": homepage,
    }
    # Documentation: match schema (list of Documentation objects)
    docs = [u for u in (c.get("urls") or []) if "docs" in str(u).lower()]
    if docs:
        entry["documentation"] = [{"url": str(u), "type": ["Manual"]} for u in docs]
    # Add tags as topic if present
    if c.get("tags"):
        entry["topic"] = [{"term": t, "uri": ""} for t in c["tags"]]
    # Optionally add homepage as link if not present in documentation
    if homepage and not any(
        homepage == d.get("url") for d in entry.get("documentation", [])
    ):
        entry.setdefault("link", []).append({"url": homepage, "type": ["Homepage"]})
    return entry


def _publication_identifiers(candidate: dict[str, Any]) -> list[str]:
    pubs = candidate.get("publication") or candidate.get("publications") or []
    identifiers: list[str] = []
    if isinstance(pubs, dict):
        pubs = [pubs]
    for pub in pubs:
        if not isinstance(pub, dict):
            continue
        for key in ("pmcid", "pmid", "doi"):
            value = pub.get(key)
            if isinstance(value, str) and value.strip():
                identifiers.append(f"{key}:{value.strip()}")
    seen: set[str] = set()
    ordered: list[str] = []
    for ident in identifiers:
        if ident not in seen:
            seen.add(ident)
            ordered.append(ident)
    return ordered


ALLOWED_ENTRY_FIELDS = set(BioToolsEntry.model_fields.keys())


def _prepare_output_structure(logger, base: Path | str = Path("out")) -> None:
    base_path = Path(base)
    base_path.mkdir(parents=True, exist_ok=True)
    for folder in ("exports", "reports", "cache", "logs", "pub2tools"):
        (base_path / folder).mkdir(parents=True, exist_ok=True)

    legacy_root = Path("out")
    if base_path.resolve() != legacy_root.resolve():
        return

    migrations = [
        (legacy_root / "payload.json", base_path / "exports" / "biotools_payload.json"),
        (legacy_root / "report.jsonl", base_path / "reports" / "assessment.jsonl"),
        (legacy_root / "report.csv", base_path / "reports" / "assessment.csv"),
        (
            legacy_root / "updated_entries.json",
            base_path / "exports" / "biotools_entries.json",
        ),
        (
            legacy_root / "enriched_candidates.json.gz",
            base_path / "cache" / "enriched_candidates.json.gz",
        ),
        (legacy_root / "ollama.log", base_path / "logs" / "ollama.log"),
    ]

    pipeline = base_path / "pipeline"
    migrations.extend(
        [
            (
                pipeline / "exports" / "biotools_payload.json",
                base_path / "exports" / "biotools_payload.json",
            ),
            (
                pipeline / "exports" / "biotools_entries.json",
                base_path / "exports" / "biotools_entries.json",
            ),
            (
                pipeline / "reports" / "assessment.jsonl",
                base_path / "reports" / "assessment.jsonl",
            ),
            (
                pipeline / "reports" / "assessment.csv",
                base_path / "reports" / "assessment.csv",
            ),
            (
                pipeline / "cache" / "enriched_candidates.json.gz",
                base_path / "cache" / "enriched_candidates.json.gz",
            ),
            (pipeline / "logs" / "ollama.log", base_path / "logs" / "ollama.log"),
        ]
    )

    for src, dest in migrations:
        if not src.exists():
            continue
        if dest.exists():
            logger.warning(
                "Legacy output %s left in place because %s already exists", src, dest
            )
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            src.rename(dest)
            logger.info("Moved legacy output from %s to %s", src, dest)
        except OSError as exc:
            logger.warning(
                "Could not migrate legacy output %s -> %s: %s", src, dest, exc
            )

    legacy_pub2tools = pipeline / "pub2tools"
    target_pub2tools = base_path / "pub2tools"
    if legacy_pub2tools.exists():
        target_pub2tools.mkdir(parents=True, exist_ok=True)
        try:
            for child in sorted(legacy_pub2tools.iterdir()):
                dest = target_pub2tools / child.name
                if dest.exists():
                    logger.warning(
                        "Legacy Pub2Tools artifact %s not moved because %s exists",
                        child,
                        dest,
                    )
                    continue
                child.rename(dest)
                logger.info(
                    "Moved legacy Pub2Tools artifact from %s to %s", child, dest
                )
        except OSError as exc:
            logger.warning("Could not migrate legacy Pub2Tools outputs: %s", exc)

    # Attempt to remove empty legacy folders
    for path in [
        pipeline / "exports",
        pipeline / "reports",
        pipeline / "cache",
        pipeline / "logs",
        pipeline / "pub2tools",
        pipeline,
    ]:
        try:
            path.rmdir()
        except OSError:
            continue


def write_updated_entries(
    records: list[tuple[dict[str, Any], dict[str, Any], str]],
    path: Path,
    *,
    config_data: dict[str, Any],
    logger,
) -> None:
    ensure_parent(path)
    payload_version = (
        config_data.get("pipeline", {}).get("payload_version") or PACKAGE_VERSION
    )
    if not records:
        PayloadWriter().write_payload([], str(path), version=payload_version)
        logger.info(
            f"📦 No accepted candidates; wrote empty updated entries payload to {path}"
        )
        return

    entries: list[BioToolsEntry] = []
    for candidate, scores, homepage in records:
        try:
            entry = build_updated_entry(candidate, scores, homepage)
            entries.append(entry)
        except Exception as exc:
            logger.warning(
                "Skipping candidate '%s' for updated entries: %s",
                candidate.get("title") or candidate.get("name") or "<unknown>",
                exc,
            )
    PayloadWriter().write_payload(entries, str(path), version=payload_version)
    logger.info(f"📦 Wrote {len(entries)} updated bio.tools entries to {path}")


def build_updated_entry(
    candidate: dict[str, Any], scores: dict[str, Any], selected_homepage: str
) -> BioToolsEntry:
    entry_data = _extract_candidate_entry_fields(candidate)

    name = scores.get("tool_name") or candidate.get("title") or candidate.get("name")
    entry_data["name"] = name or "Unnamed Tool"

    description = scores.get("concise_description") or candidate.get("description")
    entry_data["description"] = description or "Candidate tool from Pub2Tools"

    homepage = _resolve_homepage(candidate, scores, selected_homepage)
    entry_data["homepage"] = homepage
    entry_data["link"] = _ensure_homepage_link(entry_data.get("link"), homepage)

    publication_ids = scores.get("publication_ids") or candidate.get(
        "publication_ids", []
    )
    entry_data["publication"] = _merge_publications(
        entry_data.get("publication"), publication_ids
    )

    _remove_null_fields(entry_data)

    return BioToolsEntry(**entry_data)


def _extract_candidate_entry_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    entry_data: dict[str, Any] = {}
    for field in ALLOWED_ENTRY_FIELDS:
        if field in {"name", "description", "homepage"}:
            continue
        value = candidate.get(field)
        if field == "publication" and value:
            entry_data[field] = _normalize_publications(value)
        elif value is not None:
            entry_data[field] = deepcopy(value)
    return entry_data


def _merge_publications(
    existing: list[dict[str, Any]] | None, identifiers: list[str] | None
) -> list[dict[str, Any]] | None:
    pubs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pub in existing or []:
        if not isinstance(pub, dict):
            continue
        normalized = {
            key: value
            for key, value in ((k.lower(), v) for k, v in pub.items())
            if key in {"pmcid", "pmid", "doi", "type", "note", "version"} and value
        }
        if not normalized:
            continue
        pubs.append(normalized)
        for key in ("pmcid", "pmid", "doi"):
            val = normalized.get(key)
            if val:
                seen.add(f"{key}:{val}")

    for ident in identifiers or []:
        if not isinstance(ident, str) or ":" not in ident:
            continue
        key, value = ident.split(":", 1)
        key = key.lower()
        if key not in {"pmcid", "pmid", "doi"}:
            continue
        if not value:
            continue
        tag = f"{key}:{value}"
        if tag in seen:
            continue
        pubs.append({key: value})
        seen.add(tag)

    return pubs or None


def _normalize_publications(publications: list[Any]) -> list[dict[str, Any]] | None:
    if not publications:
        return None
    normalized: list[dict[str, Any]] = []
    for publication in publications:
        if not isinstance(publication, dict):
            continue
        cleaned = {
            key: value
            for key, value in ((k.lower(), v) for k, v in publication.items())
            if key in {"pmcid", "pmid", "doi", "type", "note", "version"} and value
        }
        if cleaned:
            normalized.append(cleaned)
    return normalized or None


def _ensure_homepage_link(links: Any, homepage: str) -> list[dict[str, Any]] | None:
    if not homepage:
        return links if isinstance(links, list) else None
    normalized: list[dict[str, Any]] = []
    if isinstance(links, list):
        for entry in links:
            if isinstance(entry, dict):
                normalized.append(entry)
    if not any(
        isinstance(entry, dict) and entry.get("url") == homepage for entry in normalized
    ):
        normalized.append({"url": homepage, "type": ["Homepage"]})
    return normalized


def _remove_null_fields(data: dict[str, Any]) -> None:
    for key in list(data.keys()):
        if data[key] is None:
            del data[key]


def _save_enriched_candidates(
    candidates: list[dict[str, Any]], path: Path, logger
) -> None:
    try:
        ensure_parent(path)
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(candidates, fh, ensure_ascii=False)
        logger.info("CACHE saved enriched candidates -> %s", path)
    except Exception as exc:
        logger.warning("Failed to write enriched cache %s: %s", path, exc)


def _load_enriched_candidates(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("Enriched cache is not a list of candidates")
    return [c for c in data if isinstance(c, dict)]


def _find_latest_pub2tools_export(*bases: Path) -> Path | None:
    candidates: list[tuple[float, Path]] = []
    for base in bases:
        if base is None:
            continue
        path = Path(base)
        if not path.exists():
            continue
        if path.is_file() and path.name == "to_biotools.json":
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
            continue
        direct = path / "to_biotools.json"
        if direct.exists():
            try:
                candidates.append((direct.stat().st_mtime, direct))
            except OSError:
                pass
        try:
            children = sorted(path.iterdir())
        except OSError:
            children = []
        for child in children:
            if not child.is_dir():
                continue
            export_path = child / "to_biotools.json"
            if not export_path.exists():
                continue
            try:
                candidates.append((export_path.stat().st_mtime, export_path))
            except OSError:
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _export_matches_time_period(path: Path, label: str) -> bool:
    label_prefix = f"{label}_"
    for part in path.parts:
        if part == label or part.startswith(label_prefix):
            return True
    return False


def _load_assessment_report(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:  # pragma: no cover - rare corrupt file
                raise ValueError(
                    f"Invalid assessment row at {path}:{idx}: {exc}"
                ) from exc
            if isinstance(data, dict):
                rows.append(data)
    return rows


def _build_candidate_index(
    candidates: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("id", "tool_id", "biotools_id", "biotoolsID", "identifier"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                by_id.setdefault(value.strip(), candidate)
        title = candidate.get("title") or candidate.get("name")
        if isinstance(title, str) and title.strip():
            by_title.setdefault(title.strip(), candidate)
    return by_id, by_title


def _match_candidate_from_report(
    row: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    by_title: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for key in ("id", "tool_id", "biotools_id", "biotoolsID", "identifier"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            candidate = by_id.pop(value.strip(), None)
            if candidate is not None:
                title = candidate.get("title") or candidate.get("name")
                if isinstance(title, str) and title.strip():
                    by_title.pop(title.strip(), None)
                return candidate
    title = row.get("title")
    if isinstance(title, str) and title.strip():
        candidate = by_title.pop(title.strip(), None)
        if candidate is not None:
            for key in ("id", "tool_id", "biotools_id", "biotoolsID", "identifier"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    by_id.pop(value.strip(), None)
            return candidate
    return None


def _resolve_homepage(
    candidate: dict[str, Any], scores: dict[str, Any], selected_homepage: str
) -> str:
    for source in (
        scores.get("homepage"),
        selected_homepage,
        candidate.get("homepage"),
    ):
        if isinstance(source, str) and source.strip():
            return source.strip()
    for url in candidate.get("urls") or []:
        url_str = str(url).strip()
        if url_str.startswith("http://") or url_str.startswith("https://"):
            return url_str
    return ""


def execute_run(
    from_date: str | None = None,
    to_date: str | None = None,
    min_bio_score: float = 0.6,
    min_doc_score: float = 0.6,
    limit: int | None = None,
    dry_run: bool = False,
    output: Path | None = None,
    report: Path | None = None,
    model: str | None = None,
    concurrency: int = 8,
    input_path: str | None = None,
    offline: bool = False,
    edam_owl: str | None = None,
    idf: str | None = None,
    idf_stemmed: str | None = None,
    firefox_path: str | None = None,
    p2t_cli: str | None = None,
    show_progress: bool = True,
    updated_entries: Path | None = None,
    config_data: dict[str, Any] | None = None,
    enriched_cache: Path | None = None,
    resume_from_enriched: bool = False,
    resume_from_pub2tools: bool = False,
    resume_from_scoring: bool = False,
    config_file_path: Path | None = None,
    output_root: Path | None = None,
) -> None:
    from biotoolsllmannotate.io.logging import get_logger, setup_logging

    stdout_is_tty = False
    stdout = getattr(sys, "stdout", None)
    if stdout is not None:
        isatty = getattr(stdout, "isatty", None)
        if callable(isatty):
            try:
                stdout_is_tty = bool(isatty())
            except Exception:
                stdout_is_tty = False
    if config_data is None:
        from biotoolsllmannotate.config import get_config_yaml

        config_data = get_config_yaml()
    total_steps = 5

    progress_mode_env_raw = os.environ.get("BIOTOOLS_PROGRESS", "").strip().lower()
    mode = progress_mode_env_raw or "auto"
    off_modes = {"off", "0", "false", "none", "disable", "disabled"}
    plain_modes = {"plain", "simple", "text"}
    live_modes = {"live", "rich", "fancy"}
    force_live_modes = {"force", "force-live", "live!"}
    auto_modes = {"auto", "default"}

    want_progress = show_progress and mode not in off_modes
    pytest_active = bool(os.environ.get("PYTEST_CURRENT_TEST"))

    live_enabled = False
    simple_status_enabled = False
    force_live_requested = want_progress and mode in force_live_modes
    live_fallback_reason: str | None = None

    if want_progress:
        if force_live_requested:
            live_enabled = True
        elif mode in live_modes:
            live_enabled = stdout_is_tty and not pytest_active
            if not live_enabled:
                live_fallback_reason = "no interactive terminal detected"
                simple_status_enabled = True
        elif mode in plain_modes:
            simple_status_enabled = True
        else:  # auto/default or unknown -> pick live when interactive
            auto_live = stdout_is_tty and not pytest_active
            live_enabled = auto_live
            if not live_enabled:
                live_fallback_reason = "non-interactive output"
            simple_status_enabled = not live_enabled

    if live_enabled and not force_live_requested:
        if not stdout_is_tty:
            if live_fallback_reason is None:
                live_fallback_reason = "non-interactive output"
            live_enabled = False
            simple_status_enabled = want_progress

    log_fallback_message = False
    log_force_warning = False
    if live_fallback_reason and simple_status_enabled:
        log_fallback_message = True
    elif force_live_requested and live_enabled and not stdout_is_tty:
        log_force_warning = True

    console_kwargs: dict[str, Any] = {"force_jupyter": False}
    if live_enabled or force_live_requested:
        console_kwargs.update(force_terminal=True, force_interactive=True)
    console = Console(**console_kwargs)

    setup_logging(console=console)
    logger = get_logger("pipeline")

    if log_fallback_message:
        logger.info(
            "Progress status: live mode disabled (%s); showing plain updates. Set BIOTOOLS_PROGRESS=force to override.",
            live_fallback_reason,
        )
    elif log_force_warning:
        logger.warning(
            "Progress status: forcing live display without TTY support; output may contain redraw artifacts."
        )

    def step_msg(step: int, text: str) -> str:
        return f"[Step {step}/{total_steps}] {text}"

    status_lock = Lock()
    status_lines = [
        "GATHER – initializing…",
        "DEDUP – waiting…",
        "ENRICH – waiting…",
        "SCORE – waiting…",
        "OUTPUT – waiting…",
    ]
    status_progress: list[tuple[int, int] | None] = [None] * len(status_lines)
    status_board: Live | None = None
    last_logged_statuses: list[str] | None = None

    def format_progress(current: int, total: int, width: int = 24) -> str:
        if total <= 0:
            return ""
        current = max(0, min(current, total))
        filled = int(width * current / total) if total else 0
        bar = "#" * filled + "-" * max(width - filled, 0)
        percent = (current / total) * 100 if total else 0
        return f"[{bar}] {current}/{total} ({percent:5.1f}%)"

    def compose_status(idx: int) -> str:
        base = status_lines[idx]
        progress_state = status_progress[idx]
        if progress_state:
            current, total = progress_state
            bar = format_progress(current, total)
            if bar:
                base = f"{base} {bar}"
        return base

    def render_status() -> Panel:
        table = Table.grid(padding=(0, 1))
        with status_lock:
            for idx in range(len(status_lines)):
                message = compose_status(idx)
                table.add_row(f"[bold cyan]S{idx + 1}[/] {message}")
        return Panel(table, title="Pipeline Status", border_style="cyan")

    def refresh_status(index: int | None = None) -> None:
        if status_board:
            status_board.update(render_status(), refresh=True)
        elif simple_status_enabled and last_logged_statuses is not None:
            indices = range(len(status_lines)) if index is None else [index]
            with status_lock:
                for idx in indices:
                    rendered = compose_status(idx)
                    if last_logged_statuses[idx] != rendered:
                        console.print(f"[bold cyan]S{idx + 1}[/] {rendered}")
                        last_logged_statuses[idx] = rendered

    def set_status(index: int, message: str, *, clear_progress: bool = False) -> None:
        with status_lock:
            status_lines[index] = message
            if clear_progress:
                status_progress[index] = None
        refresh_status(index)

    def update_progress(index: int, current: int, total: int) -> None:
        if total <= 0:
            with status_lock:
                status_progress[index] = None
        else:
            clamped = max(0, min(current, total))
            with status_lock:
                status_progress[index] = (clamped, total)
        refresh_status(index)

    if live_enabled:
        status_board = Live(
            render_status(),
            console=console,
            refresh_per_second=6,
            transient=True,
        )
        status_board.start()
    elif simple_status_enabled:
        with status_lock:
            last_logged_statuses = [compose_status(i) for i in range(len(status_lines))]

    try:

        fetch_from_label = from_date or "7d"
        fetch_from_dt = parse_since(fetch_from_label)
        fetch_to_dt = parse_since(to_date) if to_date else None

        base_output_root = Path(output_root) if output_root is not None else Path("out")

        from_label_date = fetch_from_dt.date().isoformat()
        to_label_date = (
            fetch_to_dt.date().isoformat()
            if fetch_to_dt
            else datetime.now(UTC).date().isoformat()
        )
        time_period_label = f"range_{from_label_date}_to_{to_label_date}"
        time_period_root = base_output_root / time_period_label
        time_period_root_abs = time_period_root.resolve()
        base_output_root_abs = base_output_root.resolve()

        if output is None:
            output = base_output_root / "exports" / "biotools_payload.json"
        if report is None:
            report = base_output_root / "reports" / "assessment.jsonl"
        if updated_entries is None:
            updated_entries = base_output_root / "exports" / "biotools_entries.json"
        if enriched_cache is None:
            enriched_cache = base_output_root / "cache" / "enriched_candidates.json.gz"

        def _rebase_to_time_period(raw: Path | str | None) -> Path | None:
            if raw is None:
                return None
            path_obj = raw if isinstance(raw, Path) else Path(raw)
            abs_path = path_obj if path_obj.is_absolute() else (Path.cwd() / path_obj)
            if abs_path.is_relative_to(time_period_root_abs):
                return abs_path
            if not abs_path.is_relative_to(base_output_root_abs):
                return abs_path if path_obj.is_absolute() else path_obj
            rel = abs_path.relative_to(base_output_root_abs)
            return time_period_root / rel

        output_path = _rebase_to_time_period(output)
        report_path = _rebase_to_time_period(report)
        updated_entries_path = _rebase_to_time_period(updated_entries)
        enriched_cache_path = _rebase_to_time_period(enriched_cache)

        if output_path is None or report_path is None:
            raise ValueError("Output and report paths must resolve to valid locations")

        output = Path(output_path)
        report = Path(report_path)
        updated_entries = Path(updated_entries_path) if updated_entries_path else None
        enriched_cache = Path(enriched_cache_path) if enriched_cache_path else None

        cached_assessment_rows: list[dict[str, Any]] | None = None
        if resume_from_scoring:
            if report.exists():
                try:
                    cached_assessment_rows = _load_assessment_report(report)
                    if cached_assessment_rows:
                        logger.info(
                            "♻️ Resumed scoring decisions from cached assessment %s with %d rows",
                            report,
                            len(cached_assessment_rows),
                        )
                    else:
                        logger.warning(
                            "--resume-from-scoring requested but cached assessment %s contained no rows; rerunning scoring",
                            report,
                        )
                        cached_assessment_rows = None
                except Exception as exc:
                    logger.warning(
                        "Failed to read cached assessment %s: %s; rerunning scoring",
                        report,
                        exc,
                    )
                    cached_assessment_rows = None
            else:
                logger.warning(
                    "--resume-from-scoring requested but assessment report not found: %s",
                    report,
                )

        time_period_root.mkdir(parents=True, exist_ok=True)
        for folder in ("exports", "reports", "cache", "logs", "pub2tools"):
            (time_period_root / folder).mkdir(parents=True, exist_ok=True)

        logging_cfg = config_data.get("logging")
        if not isinstance(logging_cfg, dict):
            logging_cfg = {}
            config_data["logging"] = logging_cfg
        llm_log_value = logging_cfg.get("llm_log")
        llm_log_path = (
            _rebase_to_time_period(llm_log_value)
            if llm_log_value is not None
            else time_period_root / "logs" / "ollama.log"
        )
        logging_cfg["llm_log"] = str(llm_log_path)

        config_snapshot_path: Path | None = None
        if config_file_path is not None:
            cfg_source = Path(config_file_path)
            if cfg_source.exists():
                try:
                    dest = time_period_root / cfg_source.name
                    shutil.copy2(cfg_source, dest)
                    config_snapshot_path = dest
                except Exception as exc:
                    logger.warning("Failed to copy config file %s: %s", cfg_source, exc)
        if config_snapshot_path is None:
            dest = time_period_root / "config.generated.yaml"
            try:
                with dest.open("w", encoding="utf-8") as fh:
                    yaml.safe_dump(config_data, fh, sort_keys=False)
                config_snapshot_path = dest
            except Exception as exc:
                logger.warning("Failed to record configuration for run: %s", exc)

        logger.info("🚀 Starting biotoolsLLMAnnotate pipeline run")
        logger.info(
            f"   📅 Pub2Tools fetch range: {fetch_from_label} to {to_date or 'now'}"
        )
        logger.info(
            "   🎯 Min scores → bio: %s, documentation: %s, Limit: %s",
            f"{min_bio_score:.2f}",
            f"{min_doc_score:.2f}",
            limit or "unlimited",
        )
        logger.info(f"   📊 Output: {output}, Report: {report}")
        logger.info(f"   🤖 Model: {model or 'default'}, Concurrency: {concurrency}")
        logger.info(f"   🗂️ Time period folder: {time_period_root}")
        if config_snapshot_path:
            logger.info(f"   📄 Config snapshot stored at {config_snapshot_path}")
        logger.info(
            f"   {'🔌 Offline mode' if offline else '🌐 Online mode (will fetch from Pub2Tools if needed)'}"
        )
        set_status(0, "GATHER – preparing input sources")
        _prepare_output_structure(logger, base_output_root)
        logger.info(step_msg(1, "Gather Pub2Tools candidates or load cached input"))

        cache_path: Path | None
        if isinstance(enriched_cache, Path):
            cache_path = enriched_cache
        elif isinstance(enriched_cache, str):
            cache_path = Path(enriched_cache)
        else:
            cache_path = None

        candidates: list[dict[str, Any]] = []
        resumed = False

        if resume_from_enriched:
            if cache_path is None:
                logger.warning(
                    "--resume-from-enriched requested but no enriched cache path configured"
                )
                set_status(0, "GATHER – cache resume skipped (no path)")
                resume_from_enriched = False
            elif not cache_path.exists():
                logger.warning(
                    "--resume-from-enriched requested but cache file not found: %s",
                    cache_path,
                )
                set_status(0, "GATHER – cache resume skipped (missing file)")
                resume_from_enriched = False
            else:
                try:
                    candidates = _load_enriched_candidates(cache_path)
                    resumed = True
                    logger.info(
                        "♻️ Resumed from enriched cache %s with %d candidates",
                        cache_path,
                        len(candidates),
                    )
                    set_status(
                        0,
                        f"GATHER – resumed {len(candidates)} candidates from cache",
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to load enriched cache %s: %s; falling back to fresh ingestion",
                        cache_path,
                        exc,
                    )
                    set_status(0, "GATHER – cache resume failed, refetching")
                    candidates = []
                    resumed = False
                    resume_from_enriched = False

        if not resumed:
            env_input = input_path or os.environ.get("BIOTOOLS_ANNOTATE_INPUT")
            if not env_input:
                env_input = os.environ.get("BIOTOOLS_ANNOTATE_JSON")
            resume_export_path: Path | None = None
            if resume_from_pub2tools and not env_input:
                resume_export_path = _find_latest_pub2tools_export(
                    time_period_root / "pub2tools",
                    base_output_root / "pub2tools",
                    time_period_root / "pipeline" / "pub2tools",
                    base_output_root / "pipeline" / "pub2tools",
                    time_period_root,
                )
                if resume_export_path and not _export_matches_time_period(
                    resume_export_path, time_period_label
                ):
                    logger.info(
                        "--resume-from-pub2tools ignoring cached export %s (mismatched time period)",
                        resume_export_path,
                    )
                    resume_export_path = None
                if resume_export_path is None:
                    logger.info(
                        "--resume-from-pub2tools requested but no cached to_biotools.json was found; attempting fresh ingestion"
                    )
                else:
                    env_input = str(resume_export_path)
            candidates = load_candidates(env_input)
            if resume_export_path is not None:
                if candidates:
                    logger.info(
                        "♻️ Resumed from cached Pub2Tools export %s with %d candidates",
                        resume_export_path,
                        len(candidates),
                    )
                    set_status(
                        0,
                        f"GATHER – reused {len(candidates)} candidates from Pub2Tools cache",
                    )
                else:
                    logger.warning(
                        "--resume-from-pub2tools requested but cached export %s was empty or invalid; falling back to Pub2Tools fetch",
                        resume_export_path,
                    )
                    env_input = None
                    candidates = []
                    resume_export_path = None
            elif env_input:
                logger.info(
                    f"INPUT file %s -> %d candidates", env_input, len(candidates)
                )
                set_status(
                    0,
                    f"GATHER – loaded {len(candidates)} candidates from input",
                )
            else:
                set_status(0, "GATHER – no local input, Pub2Tools may run")
            if not candidates and not offline:
                try:
                    from ..ingest import pub2tools_client as p2t_client

                    logger.info(
                        "FETCH Pub2Tools range %s → %s",
                        fetch_from_dt.date(),
                        (fetch_to_dt.date() if fetch_to_dt else "now"),
                    )
                    set_status(0, "GATHER – invoking Pub2Tools fetch")
                    candidates = p2t_client.fetch_via_cli(
                        fetch_from_dt,
                        to_date=fetch_to_dt,
                        limit=limit,
                        cli_path=p2t_cli,
                        edam_owl=edam_owl or "http://edamontology.org/EDAM.owl",
                        idf=idf
                        or "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
                        idf_stemmed=idf_stemmed
                        or "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
                        base_output_dir=time_period_root / "pub2tools",
                    )
                    logger.info(
                        "FETCH complete – %d candidates retrieved from Pub2Tools",
                        len(candidates),
                    )
                    set_status(
                        0,
                        f"GATHER – fetched {len(candidates)} candidates via Pub2Tools",
                    )
                except Exception as e:
                    logger.warning(f"Pub2Tools fetch with date range failed: {e}")
                    set_status(0, "GATHER – Pub2Tools fetch failed")
                    candidates = candidates or []

        if candidates:
            logger.info(step_msg(2, "DEDUP – Filter candidate list"))
            set_status(1, f"DEDUP – processing {len(candidates)} candidates")
            try:
                from ..ingest import pub2tools_fetcher as pf

                candidates = pf.filter_and_normalize(candidates)
                logger.info(
                    "DEDUP kept %d unique candidates after normalization",
                    len(candidates),
                )
                set_status(1, f"DEDUP – kept {len(candidates)} unique candidates")
            except Exception as e:
                logger.warning(f"Deduplication failed: {e}")
                kept: list[dict[str, Any]] = []
                seen: set[tuple[str, str]] = set()
                for c in candidates:
                    homepage = primary_homepage(c.get("urls", [])) or ""
                    key = (str(c.get("title") or ""), homepage)
                    if key in seen:
                        continue
                    seen.add(key)
                    kept.append(c)
                candidates = kept
                logger.info("DEDUP fallback kept %d unique candidates", len(candidates))
                set_status(
                    1, f"DEDUP – fallback kept {len(candidates)} unique candidates"
                )
        else:
            set_status(1, "DEDUP – no candidates available")

        if candidates and enriched_cache and not resume_from_enriched:
            _save_enriched_candidates(candidates, enriched_cache, logger)

        if limit is not None:
            candidates = candidates[: max(0, int(limit))]
            logger.info("LIMIT applied – processing %d candidates", len(candidates))
            set_status(1, f"DEDUP – limit applied, {len(candidates)} remain")

        enrichment_cfg = config_data.get("enrichment", {}) or {}
        homepage_cfg = enrichment_cfg.get("homepage", {}) or {}
        europe_pmc_cfg = enrichment_cfg.get("europe_pmc", {}) or {}

        if candidates:
            logger.info(step_msg(3, "ENRICH – Homepage & publication evidence"))
        else:
            logger.info(step_msg(3, "ENRICH – skipped (no candidates)"))
            set_status(2, "ENRICH – skipped (no candidates)")

        if (
            candidates
            and not offline
            and not resume_from_enriched
            and homepage_cfg.get("enabled", True)
        ):
            logger.info(
                "SCRAPE homepage metadata for %d candidates (timeout=%ss)",
                len(candidates),
                homepage_cfg.get("timeout", 8),
            )
            set_status(2, f"SCRAPE – scanning {len(candidates)} homepages")
            update_progress(2, 0, len(candidates))
            scraped_count = 0
            for idx, candidate in enumerate(candidates, start=1):
                scrape_homepage_metadata(candidate, config=homepage_cfg, logger=logger)
                if candidate.get("homepage_scraped"):
                    scraped_count += 1
                update_progress(2, idx, len(candidates))
            logger.info(
                "SCRAPE completed – %d/%d candidates processed",
                scraped_count,
                len(candidates),
            )
            set_status(
                2,
                f"SCRAPE – completed {scraped_count}/{len(candidates)} homepages",
                clear_progress=True,
            )
        elif candidates:
            reason = (
                "offline mode"
                if offline
                else ("cache reuse" if resume_from_enriched else "disabled")
            )
            logger.info(f"SCRAPE skipped – {reason}")
            set_status(2, f"SCRAPE – skipped ({reason})")

        enrichment_active = (
            candidates
            and not offline
            and not resume_from_enriched
            and europe_pmc_cfg.get("enabled", True)
        )
        if candidates and enrichment_active:
            try:
                from biotoolsllmannotate.enrich import enrich_candidates_with_europe_pmc

                total_europe = len(candidates)
                set_status(
                    2,
                    f"ENRICH – Europe PMC processing {total_europe} candidates",
                )
                update_progress(2, 0, total_europe)

                enrich_candidates_with_europe_pmc(
                    candidates,
                    config=europe_pmc_cfg,
                    logger=logger,
                    offline=offline,
                    progress_callback=lambda completed, total: update_progress(
                        2, completed, total or total_europe
                    ),
                )
                logger.info(
                    "ENRICH completed – Europe PMC metadata added where available"
                )
                set_status(2, "ENRICH – Europe PMC metadata added", clear_progress=True)
                if enriched_cache and not resume_from_enriched:
                    _save_enriched_candidates(candidates, Path(enriched_cache), logger)
            except Exception as exc:
                logger.warning(f"Europe PMC enrichment skipped due to error: {exc}")
                set_status(
                    2, "ENRICH – Europe PMC error, see logs", clear_progress=True
                )
        elif candidates and not enrichment_active:
            if offline:
                logger.info("ENRICH Europe PMC skipped – offline mode enabled")
                set_status(2, "ENRICH – Europe PMC skipped (offline)")
            elif resume_from_enriched:
                logger.info("ENRICH Europe PMC skipped – enriched cache reuse")
                set_status(2, "ENRICH – Europe PMC skipped (cache)")
            else:
                logger.info("ENRICH Europe PMC skipped – disabled in config")
                set_status(2, "ENRICH – Europe PMC skipped (disabled)")

        payload: list[dict[str, Any]] = []
        report_rows: list[dict[str, Any]] = []
        accepted_records: list[tuple[dict[str, Any], dict[str, Any], str]] = []

        logger.info(
            step_msg(
                4,
                f"SCORE – {len(candidates)} candidates using {model or 'default'} scoring",
            )
        )
        total_candidates = len(candidates)
        if total_candidates == 0:
            set_status(3, "SCORE – skipped (no candidates)")
        else:
            set_status(3, f"SCORE – preparing {total_candidates} candidates")
            update_progress(3, 0, total_candidates)

        scoring_resumed = bool(cached_assessment_rows)
        if scoring_resumed and not candidates:
            logger.warning(
                "--resume-from-scoring requested but no enriched candidates were available; rerunning scoring"
            )
            scoring_resumed = False

        score_fallbacks = {"llm": 0, "health": 0}
        score_duration = 0.0
        total_scored = 0
        accepted_count = 0
        rejected_count = 0

        if scoring_resumed:
            by_id, by_title = _build_candidate_index(candidates)
            unmatched_report_rows = 0
            for cached_row in cached_assessment_rows or []:
                row = deepcopy(cached_row)
                scores = row.get("scores") or {}
                homepage = str(row.get("homepage") or "").strip()
                candidate = _match_candidate_from_report(row, by_id, by_title)
                if candidate is None:
                    include = include_candidate(
                        scores,
                        min_bio_score=min_bio_score,
                        min_doc_score=min_doc_score,
                        has_homepage=bool(homepage),
                    )
                    row["include"] = include
                    unmatched_report_rows += 1
                    report_rows.append(row)
                    continue
                urls = [str(u) for u in (candidate.get("urls") or [])]
                if not homepage:
                    homepage = candidate.get("homepage") or primary_homepage(urls) or ""
                include = include_candidate(
                    scores,
                    min_bio_score=min_bio_score,
                    min_doc_score=min_doc_score,
                    has_homepage=bool(homepage),
                )
                row["homepage"] = homepage
                row["include"] = include
                report_rows.append(row)
                if include:
                    payload.append(to_entry(candidate, homepage))
                    accepted_records.append((candidate, scores, homepage))
            total_scored = len(report_rows)
            accepted_count = len(accepted_records)
            rejected_count = max(total_scored - accepted_count, 0)
            score_duration = 0.0
            if unmatched_report_rows:
                logger.warning(
                    "Resume scoring skipped %d cached assessment rows because no matching enriched candidate was found",
                    unmatched_report_rows,
                )
            logger.info(
                "RESUME scoring reused %d decisions (%d accepted, %d rejected)",
                total_scored,
                accepted_count,
                rejected_count,
            )
            set_status(
                3,
                f"SCORE – reused cached assessment ({accepted_count} accepted, {rejected_count} rejected)",
                clear_progress=True,
            )
            logger.info("TIMING score_elapsed_seconds=%.3f", score_duration)
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def heuristic_score_one(c: dict[str, Any]):
                urls = [str(u) for u in (c.get("urls") or [])]
                homepage = c.get("homepage") or primary_homepage(urls) or ""
                publication_ids = _publication_identifiers(c)
                if publication_ids:
                    c.setdefault("publication_ids", publication_ids)
                candidate_id = (
                    c.get("id")
                    or c.get("tool_id")
                    or c.get("biotools_id")
                    or c.get("biotoolsID")
                    or c.get("identifier")
                    or ""
                )
                title = (
                    c.get("title")
                    or c.get("name")
                    or c.get("tool_title")
                    or c.get("display_title")
                    or ""
                )
                scores = simple_scores(c)
                scores.setdefault("model", "heuristic")
                include = include_candidate(
                    scores,
                    min_bio_score=min_bio_score,
                    min_doc_score=min_doc_score,
                    has_homepage=bool(homepage),
                )
                decision = {
                    "id": str(candidate_id),
                    "title": str(title),
                    "homepage": homepage,
                    "publication_ids": publication_ids,
                    "scores": scores,
                    "include": include,
                }
                return (decision, c, homepage, include)

            use_llm = not offline
            scorer = None

            if use_llm:
                from biotoolsllmannotate.assess.scorer import Scorer

                scorer = Scorer(model=model, config=config_data)
                client = getattr(scorer, "client", None)
                if client is not None and hasattr(client, "ping"):
                    healthy, health_error = client.ping()
                else:  # pragma: no cover - only hit in heavily mocked tests
                    healthy, health_error = True, None
                if not healthy:
                    score_fallbacks["health"] = 1
                    use_llm = False
                    logger.warning(
                        "LLM health check failed (%s). Using heuristic scoring for this run; consider --offline if repeating.",
                        health_error,
                    )
                    set_status(3, "SCORE – heuristic fallback (LLM unavailable)")

            if not use_llm:
                if offline and total_candidates:
                    set_status(3, "SCORE – heuristic scoring (offline mode)")

                def score_one(c):
                    return heuristic_score_one(c)

            else:

                def score_one(c):
                    urls = [str(u) for u in (c.get("urls") or [])]
                    homepage = c.get("homepage") or primary_homepage(urls) or ""
                    publication_ids = _publication_identifiers(c)
                    if publication_ids:
                        c.setdefault("publication_ids", publication_ids)
                    candidate_id = (
                        c.get("id")
                        or c.get("tool_id")
                        or c.get("biotools_id")
                        or c.get("biotoolsID")
                        or c.get("identifier")
                        or ""
                    )
                    title = (
                        c.get("title")
                        or c.get("name")
                        or c.get("tool_title")
                        or c.get("display_title")
                        or ""
                    )
                    try:
                        scores = scorer.score_candidate(c)
                    except Exception as exc:
                        score_fallbacks["llm"] += 1
                        logger.warning(
                            "LLM scoring failed for '%s': %s. Using heuristic backup; rerun with --offline or check Ollama service.",
                            title or candidate_id or "<unknown>",
                            exc,
                        )
                        set_status(
                            3, "SCORE – temporary LLM failure, heuristics applied"
                        )
                        return heuristic_score_one(c)
                    include = include_candidate(
                        scores,
                        min_bio_score=min_bio_score,
                        min_doc_score=min_doc_score,
                        has_homepage=bool(homepage),
                    )
                    decision = {
                        "id": str(candidate_id),
                        "title": str(title),
                        "homepage": homepage,
                        "publication_ids": publication_ids,
                        "scores": scores,
                        "include": include,
                    }
                    return (decision, c, homepage, include)

            score_start = perf_counter()
            try:
                if total_candidates:
                    update_interval = max(1, total_candidates // 20)
                    processed = 0
                    with ThreadPoolExecutor(max_workers=concurrency) as executor:
                        futures = [executor.submit(score_one, c) for c in candidates]
                        for fut in as_completed(futures):
                            decision, c, homepage, include = fut.result()
                            processed += 1
                            report_rows.append(decision)
                            scores = decision.get("scores", {})
                            if include:
                                payload.append(to_entry(c, homepage))
                                accepted_records.append((c, scores, homepage))
                            update_progress(3, processed, total_candidates)
                            if (
                                processed % update_interval == 0
                                or processed == total_candidates
                            ):
                                set_status(
                                    3,
                                    f"SCORE – processed {processed}/{total_candidates} candidates",
                                )
                else:
                    processed = 0
            finally:
                score_duration = perf_counter() - score_start

            accepted_count = len(accepted_records)
            total_scored = len(candidates)
            rejected_count = max(total_scored - accepted_count, 0)
            logger.info(
                "SUMMARY score=%d accepted=%d rejected=%d llm_fallbacks=%d llm_health_fail=%d duration=%.2fs",
                total_scored,
                accepted_count,
                rejected_count,
                score_fallbacks.get("llm", 0),
                score_fallbacks.get("health", 0),
                score_duration,
            )
            logger.info("TIMING score_elapsed_seconds=%.3f", score_duration)
            set_status(
                3,
                f"SCORE – complete in {score_duration:.1f}s ({accepted_count} accepted, {rejected_count} rejected)",
                clear_progress=True,
            )

        logger.info(step_msg(5, "OUTPUT – Write reports and bio.tools payload"))
        set_status(4, "OUTPUT – writing reports")
        logger.info(f"📝 Writing report to {report}")
        write_jsonl(report, report_rows)
        report_csv = report.with_suffix(".csv")
        logger.info(f"📝 Writing CSV report to {report_csv}")
        write_report_csv(report_csv, report_rows)

        invalids = []
        for entry in payload:
            try:
                BioToolsEntry(**entry)
            except Exception as e:
                invalids.append({"entry": entry, "error": str(e)})

        if not dry_run:
            logger.info(f"OUTPUT payload -> {output}")
            set_status(4, "OUTPUT – writing payload")
            write_json(output, payload)
            updated_path = updated_entries or output.with_name("biotools_entries.json")
            write_updated_entries(
                accepted_records,
                updated_path,
                config_data=config_data,
                logger=logger,
            )
        else:
            set_status(4, "OUTPUT – dry-run (payload skipped)")

        if invalids:
            logger.error(
                f"Payload validation failed for {len(invalids)} entries. See report for details."
            )
            write_json(output.with_suffix(".invalid.json"), invalids)
            set_status(4, "OUTPUT – validation failed, see *.invalid.json")
            sys.exit(2)

        logger.info("🎉 Pipeline run complete!")
        set_status(4, "OUTPUT – complete")
    finally:
        if status_board:
            status_board.stop()
    return
