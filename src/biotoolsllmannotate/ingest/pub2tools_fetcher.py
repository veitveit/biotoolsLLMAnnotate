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
    candidates: Iterable[dict[str, Any]], since: datetime
) -> list[dict[str, Any]]:
    """Filter candidates newer than `since` and deduplicate by (title, homepage).

    - Keeps the first occurrence of a (normalized_title, homepage) pair.
    - Drops entries with `published_at` older than `since` when timestamp exists.
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
        if ts is not None and ts < since:
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
        return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []
