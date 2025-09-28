from __future__ import annotations

"""Pub2Tools ingestion helpers.

This module provides utilities to load candidate tools from Pub2Tools outputs
and to filter/deduplicate them prior to assessment.

Network fetching is intentionally not implemented here yet; during tests and
local development we read a JSON array from the file path provided by the
environment variable `BIOTOOLS_ANNOTATE_INPUT`.
"""

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_EDAM_FIELDS = ("topic", "data", "operation", "format")
_EDAM_TERM_KEYS = ("term", "label", "name")


def merge_edam_tags(candidate: dict[str, Any]) -> None:
    """Ensure candidate['tags'] includes EDAM term names from topic/data/operation/format."""

    existing: list[str] = []
    seen: set[str] = set()

    for value in candidate.get("tags") or []:
        text = str(value).strip()
        if not text:
            continue
        existing.append(text)
        seen.add(text.lower())

    def _collect_terms(value: Any) -> list[str]:
        terms: list[str] = []
        if value is None:
            return terms
        if isinstance(value, dict):
            for key in _EDAM_TERM_KEYS:
                term_value = value.get(key)
                if isinstance(term_value, str) and term_value.strip():
                    terms.append(term_value.strip())
                    break
        elif isinstance(value, str):
            if value.strip():
                terms.append(value.strip())
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            for item in value:
                terms.extend(_collect_terms(item))
        return terms

    tags = list(existing)

    def _add_term(term: str) -> None:
        key = term.lower()
        if key not in seen:
            tags.append(term)
            seen.add(key)

    for field in _EDAM_FIELDS:
        for term in _collect_terms(candidate.get(field)):
            _add_term(term)

    for func in candidate.get("function") or []:
        if not isinstance(func, dict):
            continue
        for term in _collect_terms(func.get("operation")):
            _add_term(term)
        for port_key in ("input", "output"):
            for port in func.get(port_key) or []:
                if not isinstance(port, dict):
                    continue
                for term in _collect_terms(port.get("data")):
                    _add_term(term)
                for term in _collect_terms(port.get("format")):
                    _add_term(term)

    if tags:
        candidate["tags"] = tags
    elif "tags" in candidate:
        candidate["tags"] = []


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1]
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _normalize_url(u: str) -> str:
    u = (u or "").strip()
    if u.startswith("//"):
        return "https:" + u
    return u


def _homepage(urls: Iterable[str]) -> str:
    for u in urls:
        nu = _normalize_url(str(u))
        if nu.startswith("http://") or nu.startswith("https://"):
            return nu
    return ""


def filter_and_normalize(
    candidates: Iterable[dict[str, Any]], since: datetime | None = None
) -> list[dict[str, Any]]:
    """Deduplicate candidates by (title, homepage) and optionally filter by date.

    - Keeps the first occurrence of a (normalized_title, homepage) pair.
    - When ``since`` is provided, drops entries whose ``published_at`` precedes it.
    - Returns shallow-normalized dicts preserving original keys.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for c in candidates:
        title = str(c.get("title") or c.get("name") or "").strip()
        if not title:
            # Skip items without a sensible title
            continue
        ts = _parse_dt(c.get("published_at"))
        if since is not None and ts is not None and ts < since:
            continue
        urls = [str(u) for u in (c.get("urls") or [])]
        homepage = _homepage(urls)

        key = (title, homepage)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def load_from_env_file(path: Path) -> list[dict[str, Any]]:
    """Load candidates from a local JSON file (array of objects)."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items: list[dict[str, Any]] = []
        for raw in data if isinstance(data, list) else []:
            if isinstance(raw, dict):
                merge_edam_tags(raw)
                items.append(raw)
        if isinstance(data, dict):
            candidate_list = data.get("list")
            if isinstance(candidate_list, list):
                for raw in candidate_list:
                    if isinstance(raw, dict):
                        merge_edam_tags(raw)
                        items.append(raw)
        return items
    except Exception:
        return []
