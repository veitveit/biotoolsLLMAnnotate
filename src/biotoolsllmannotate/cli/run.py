from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from biotoolsllmannotate import __version__ as PACKAGE_VERSION
from biotoolsllmannotate.io.payload_writer import PayloadWriter
from biotoolsllmannotate.schema.models import BioToolsEntry


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
        return [x for x in candidates if isinstance(x, dict)]
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
        "documentation_score",
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
            writer.writerow(
                {
                    "id": row.get("id", ""),
                    "title": row.get("title", ""),
                    "tool_name": scores.get("tool_name", ""),
                    "homepage": row.get("homepage", ""),
                    "publication_ids": ", ".join(row.get("publication_ids", []) or []),
                    "include": row.get("include", False),
                    "bio_score": scores.get("bio_score", ""),
                    "documentation_score": scores.get("documentation_score", ""),
                    "concise_description": scores.get("concise_description", ""),
                    "rationale": scores.get("rationale", ""),
                    "model": scores.get("model", ""),
                    "origin_types": ", ".join(scores.get("origin_types", [])),
                }
            )


def include_candidate(
    scores: dict[str, Any], min_score: float, has_homepage: bool
) -> bool:
    return (
        scores.get("bio_score", 0.0) >= min_score
        and scores.get("documentation_score", 0.0) >= min_score
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
            if key in {"pmcid", "pmid", "doi", "type", "note", "version"}
            and value
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
            if key in {"pmcid", "pmid", "doi", "type", "note", "version"}
            and value
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
    if not any(isinstance(entry, dict) and entry.get("url") == homepage for entry in normalized):
        normalized.append({"url": homepage, "type": ["Homepage"]})
    return normalized


def _remove_null_fields(data: dict[str, Any]) -> None:
    for key in list(data.keys()):
        if data[key] is None:
            del data[key]


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
    min_score: float = 0.6,
    limit: int | None = None,
    dry_run: bool = False,
    output: Path = Path("out/payload.json"),
    report: Path = Path("out/report.jsonl"),
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
) -> None:
    from biotoolsllmannotate.io.logging import get_logger, setup_logging

    setup_logging()
    logger = get_logger("pipeline")
    if config_data is None:
        from biotoolsllmannotate.config import get_config_yaml

        config_data = get_config_yaml()
    logger.info("🚀 Starting biotoolsLLMAnnotate pipeline run")
    logger.info(f"   📅 Date range: {from_date or '7d'} to {to_date or 'now'}")
    logger.info(f"   🎯 Min score: {min_score}, Limit: {limit or 'unlimited'}")
    logger.info(f"   📊 Output: {output}, Report: {report}")
    logger.info(f"   🤖 Model: {model or 'default'}, Concurrency: {concurrency}")
    logger.info(
        f"   {'🔌 Offline mode' if offline else '🌐 Online mode (will fetch from Pub2Tools if needed)'}"
    )
    """Fetch from Pub2Tools, assess, improve, and emit outputs (stub pipeline)."""
    _since = parse_since(from_date or "7d")
    _to = parse_since(to_date) if to_date else datetime.now(UTC)
    # Advanced input path preference
    env_input = input_path or os.environ.get("BIOTOOLS_ANNOTATE_INPUT")
    if not env_input:
        # Allow config-driven override without re-running Pub2Tools
        env_input = os.environ.get("BIOTOOLS_ANNOTATE_JSON")
    candidates = load_candidates(env_input)
    if env_input:
        logger.info(
            f"📁 Loaded {len(candidates)} candidates from input file: {env_input}"
        )
    else:
        logger.info(f"📁 No input file provided, will fetch from Pub2Tools if needed")
    # If no local input provided, try Pub2Tools with date range if from_date/to_date are set
    if not candidates and not offline and (from_date or to_date):
        try:
            from ..ingest import pub2tools_client as p2t_client

            # Parse from_date and to_date
            from_date_dt = parse_since(from_date) if from_date else _since
            to_date_dt = parse_since(to_date) if to_date else _to

            logger.info(
                f"🔍 Fetching candidates from Pub2Tools for date range: {from_date_dt.date()} to {to_date_dt.date()}"
            )
            candidates = p2t_client.fetch_via_cli(
                from_date_dt,
                to_date=to_date_dt,
                limit=limit,
                cli_path=p2t_cli,
                edam_owl=edam_owl or "http://edamontology.org/EDAM.owl",
                idf=idf
                or "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
                idf_stemmed=idf_stemmed
                or "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
            )
            logger.info(f"✅ Fetched {len(candidates)} candidates from Pub2Tools")
        except Exception as e:
            logger.warning(f"Pub2Tools fetch with date range failed: {e}")
            candidates = candidates or []

    # Filter by time and deduplicate
    if candidates:
        try:
            from ..ingest import pub2tools_fetcher as pf

            candidates = pf.filter_and_normalize(candidates, _since)
            logger.info(f"🧹 Filtered and deduplicated to {len(candidates)} candidates")
        except Exception as e:
            logger.warning(f"Deduplication failed: {e}")
            kept: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for c in candidates:
                ts = candidate_published_at(c)
                if ts is not None and ts < _since:
                    continue
                homepage = primary_homepage(c.get("urls", [])) or ""
                key = (str(c.get("title") or ""), homepage)
                if key in seen:
                    continue
                seen.add(key)
                kept.append(c)
            candidates = kept
            logger.info(
                f"🧹 Deduplicated to {len(candidates)} candidates (fallback logic)"
            )

    if limit is not None:
        candidates = candidates[: max(0, int(limit))]
        logger.info(f"✂️ Limited to {len(candidates)} candidates after applying limit")

    # Enrich with publication data from Europe PMC when available
    europe_pmc_cfg = (config_data.get("enrichment", {}) or {}).get("europe_pmc", {})
    if (
        candidates
        and not offline
        and europe_pmc_cfg.get("enabled", True)
    ):
        try:
            from biotoolsllmannotate.enrich import enrich_candidates_with_europe_pmc

            enrich_candidates_with_europe_pmc(
                candidates,
                config=europe_pmc_cfg,
                logger=logger,
                offline=offline,
            )
            logger.info("📚 Enriched candidates with Europe PMC metadata where available")
        except Exception as exc:
            logger.warning(f"Europe PMC enrichment skipped due to error: {exc}")

    payload: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    accepted_records: list[tuple[dict[str, Any], dict[str, Any], str]] = []

    logger.info(
        f"🧠 Scoring {len(candidates)} candidates using {model or 'default'} model..."
    )
    from biotoolsllmannotate.assess.scorer import Scorer

    scorer = Scorer(model=model, config=config_data)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    progress: Progress | None = None
    task_id: int | None = None

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
        scores = scorer.score_candidate(c)
        include = include_candidate(
            scores, min_score=min_score, has_homepage=bool(homepage)
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

    try:
        if show_progress and candidates:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                transient=True,
            )
            progress.start()
            task_id = progress.add_task(
                "Scoring candidates", total=len(candidates)
            )

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(score_one, c) for c in candidates]
            for idx, fut in enumerate(as_completed(futures), 1):
                decision, c, homepage, include = fut.result()
                report_rows.append(decision)
                scores = decision.get("scores", {})
                if include:
                    payload.append(to_entry(c, homepage))
                    accepted_records.append((c, scores, homepage))
                if progress and task_id is not None:
                    progress.update(task_id, advance=1)
                elif idx % 10 == 0 or idx == len(candidates):
                    logger.info(
                        f"📈 Progress: {idx}/{len(candidates)} candidates scored"
                    )
    finally:
        if progress:
            progress.stop()

    # Always write report
    logger.info(f"📝 Writing report to {report}")
    write_jsonl(report, report_rows)
    report_csv = report.with_suffix(".csv")
    logger.info(f"📝 Writing CSV report to {report_csv}")
    write_report_csv(report_csv, report_rows)

    # Validate payload entries against schema
    from biotoolsllmannotate.schema.models import BioToolsEntry

    invalids = []
    for entry in payload:
        try:
            BioToolsEntry(**entry)
        except Exception as e:
            invalids.append({"entry": entry, "error": str(e)})

    # Write payload unless dry-run (spec: dry-run emits only report)
    if not dry_run:
        logger.info(f"💾 Writing payload to {output}")
        write_json(output, payload)
        updated_path = updated_entries or output.with_name("updated_entries.json")
        write_updated_entries(
            accepted_records,
            updated_path,
            config_data=config_data,
            logger=logger,
        )

    if invalids:
        logger.error(
            f"Payload validation failed for {len(invalids)} entries. See report for details."
        )
        # Optionally, write invalids to a separate file for debugging
        write_json(output.with_suffix(".invalid.json"), invalids)
        import sys

        sys.exit(2)

    logger.info("🎉 Pipeline run complete!")
    # Typer returns 0 by default when no exception; ensure files exist
    return
