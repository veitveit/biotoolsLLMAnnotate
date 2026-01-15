from __future__ import annotations

import csv
import gzip
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Iterable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any, Literal

import yaml
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from biotoolsllmannotate.enrich import (
    is_probable_publication_url,
    normalize_candidate_homepage,
    scrape_homepage_metadata,
)
from biotoolsllmannotate.ingest.pub2tools_fetcher import merge_edam_tags
from biotoolsllmannotate.io.biotools_api import (
    create_biotools_entry,
    fetch_biotools_entry,
    read_biotools_token,
)
from biotoolsllmannotate.registry import BioToolsRegistry, load_registry_from_pub2tools
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
        merged: list[dict[str, Any]] = []
        for raw in candidates:
            if isinstance(raw, dict):
                merge_edam_tags(raw)
                normalize_candidate_homepage(raw)
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


def generate_biotools_id(tool_name: str) -> str:
    """Generate a bio.tools-compatible ID from a tool name.

    Converts to lowercase, replaces spaces and special chars with hyphens/underscores,
    and removes consecutive separators.

    Examples:
        "DeepRank-GNN-esm" -> "deeprank-gnn-esm"
        "ARCTIC-3D" -> "arctic-3d"
        "My Tool Name" -> "my_tool_name"

    """
    if not tool_name:
        return ""

    # Convert to lowercase
    id_str = tool_name.lower()

    # Replace spaces with underscores
    id_str = id_str.replace(" ", "_")

    # Keep only alphanumeric, hyphens, and underscores
    id_str = re.sub(r"[^a-z0-9_-]", "", id_str)

    # Remove consecutive separators
    id_str = re.sub(r"[-_]+", lambda m: m.group(0)[0], id_str)

    # Remove leading/trailing separators
    id_str = id_str.strip("-_")

    return id_str


def primary_homepage(urls: Iterable[str]) -> str | None:
    for u in urls:
        nu = normalize_url(str(u))
        if not (nu.startswith("http://") or nu.startswith("https://")):
            continue
        if is_probable_publication_url(nu):
            continue
        return nu
    return None


def _resolve_scoring_homepage(candidate: dict[str, Any]) -> tuple[str, str | None]:
    raw_homepage = str(candidate.get("homepage") or "").strip()
    urls = [str(u).strip() for u in (candidate.get("urls") or [])]

    if raw_homepage and not is_probable_publication_url(raw_homepage):
        candidate["homepage"] = raw_homepage
        return raw_homepage, None

    alt_homepage = primary_homepage(urls) or ""
    if alt_homepage:
        candidate["homepage"] = alt_homepage
        return alt_homepage, None

    if raw_homepage:
        candidate.pop("homepage", None)
        return "", "publication_url"
    if any(is_probable_publication_url(url) for url in urls):
        candidate.pop("homepage", None)
        return "", "publication_url"
    candidate.pop("homepage", None)
    return "", "missing_homepage"


def _origin_types(candidate: dict[str, Any]) -> list[str]:
    mapping = [
        ("title", "title"),
        ("description", "description"),
        ("homepage", "homepage"),
        ("documentation", "documentation"),
        ("repository", "repository"),
        ("tags", "tags"),
        ("published_at", "publication"),
        ("publication_abstract", "publication_abstract"),
        ("publication_full_text", "publication_full_text"),
        ("publication_full_text_url", "publication_full_text_url"),
        ("publication_ids", "publication_ids"),
    ]

    def has_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set)):
            return any(str(item).strip() for item in value)
        return True

    origins: list[str] = []
    for key, label in mapping:
        if has_value(candidate.get(key)):
            origins.append(label)
    return origins


def _zero_score_payload(
    candidate: dict[str, Any],
    *,
    homepage: str,
    reason: str,
) -> dict[str, Any]:
    publication_ids = candidate.get("publication_ids")
    if not publication_ids:
        publication_ids = _publication_identifiers(candidate)
        if publication_ids:
            candidate["publication_ids"] = publication_ids

    rationale_lookup = {
        "publication_url": "Homepage unavailable for scoring (only publication links).",
        "missing_homepage": "Homepage unavailable for scoring (no homepage provided).",
    }
    rationale = rationale_lookup.get(reason, "Homepage unavailable for scoring.")

    zero_bio = {key: 0.0 for key in ("A1", "A2", "A3", "A4", "A5")}
    zero_doc = {key: 0.0 for key in ("B1", "B2", "B3", "B4", "B5")}

    return {
        "tool_name": candidate.get("title")
        or candidate.get("name")
        or candidate.get("tool_id")
        or "",
        "homepage": homepage,
        "publication_ids": publication_ids or [],
        "bio_score": 0.0,
        "bio_subscores": zero_bio,
        "documentation_score": 0.0,
        "documentation_subscores": zero_doc,
        "concise_description": (candidate.get("description") or "").strip()[:280],
        "rationale": rationale,
        "model": "rule:no-homepage",
        "model_params": {"reason": reason},
        "origin_types": _origin_types(candidate),
        "confidence_score": 0.1,
    }


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
    homepage = primary_homepage(urls)
    has_homepage = homepage is not None
    bio = 0.8 if bio_kw else 0.4
    docs = 0.8 if has_homepage else 0.1
    confidence = 0.6 if docs >= 0.5 else 0.3
    bio_subscores = {
        "A1": 1.0 if bio_kw else 0.0,
        "A2": 0.5 if bio_kw else 0.0,
        "A3": 0.5 if bio_kw else 0.0,
        "A4": 1.0 if has_homepage else 0.0,
        "A5": 0.5 if bio_kw else 0.0,
    }
    if not bio_kw:
        bio_subscores = {key: 0.0 for key in ("A1", "A2", "A3", "A4", "A5")}

    if has_homepage:
        doc_subscores = {
            "B1": 1.0,
            "B2": 1.0,
            "B3": 0.5,
            "B4": 0.5,
            "B5": 0.5,
        }
    else:
        doc_subscores = {key: 0.0 for key in ("B1", "B2", "B3", "B4", "B5")}

    return {
        "bio_score": max(0.0, min(1.0, float(bio))),
        "bio_subscores": bio_subscores,
        "documentation_score": max(0.0, min(1.0, float(docs))),
        "documentation_subscores": doc_subscores,
        "concise_description": (c.get("description") or "").strip()[:280],
        "rationale": "heuristic pre-LLM scoring",
        "confidence_score": confidence,
    }


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_invalid_json(path: Path, invalid_entries: list[dict]) -> None:
    ensure_parent(path)
    # Write invalid entries and their errors
    path.write_text(json.dumps(invalid_entries, indent=2), encoding="utf-8")


def _strip_null_fields(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if item is None:
                continue
            cleaned_item = _strip_null_fields(item)
            if cleaned_item is None:
                continue
            cleaned[key] = cleaned_item
        return cleaned
    if isinstance(value, list):
        cleaned_list: list[Any] = []
        for item in value:
            if item is None:
                continue
            cleaned_item = _strip_null_fields(item)
            if cleaned_item is None:
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list
    if isinstance(value, tuple):
        cleaned_items = []
        for item in value:
            if item is None:
                continue
            cleaned_item = _strip_null_fields(item)
            if cleaned_item is None:
                continue
            cleaned_items.append(cleaned_item)
        return tuple(cleaned_items)
    return value


def write_report_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_parent(path)
    fieldnames = [
        "manual_decision",
        "id",
        "title",
        "tool_name",
        "homepage",
        "homepage_status",
        "homepage_error",
        "publication_ids",
        "include",
        "in_biotools_name",
        "in_biotools",
        "bio_score",
        "bio_A1",
        "bio_A2",
        "bio_A3",
        "bio_A4",
        "bio_A5",
        "documentation_score",
        "confidence_score",
        "doc_B1",
        "doc_B2",
        "doc_B3",
        "doc_B4",
        "doc_B5",
        "concise_description",
        "rationale",
        "model",
        "origin_types",
        "biotools_api_status",
        "api_name",
        "api_status",
        "api_description",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            scores = row.get("scores") or {}
            bio_subscores = scores.get("bio_subscores") or {}
            doc_subscores = scores.get("documentation_subscores") or {}
            in_registry_value = row.get("in_biotools")
            name_registry_value = row.get("in_biotools_name")
            publication_ids = row.get("publication_ids")
            if isinstance(publication_ids, (list, tuple)):
                publication_ids_str = ", ".join(str(p) for p in publication_ids if p)
            elif publication_ids:
                publication_ids_str = str(publication_ids)
            else:
                publication_ids_str = ""

            origin_types_value = scores.get("origin_types")
            if isinstance(origin_types_value, (list, tuple)):
                origin_types_str = ", ".join(str(v) for v in origin_types_value if v)
            elif origin_types_value:
                origin_types_str = str(origin_types_value)
            else:
                origin_types_str = ""
            decision_value = row.get("include")
            if isinstance(decision_value, bool):
                decision_str = "add" if decision_value else "do_not_add"
            elif decision_value is None:
                decision_str = ""
            else:
                decision_str = str(decision_value)

            writer.writerow(
                {
                    "manual_decision": row.get("manual_decision", ""),
                    "id": row.get("id", ""),
                    "title": row.get("title", ""),
                    "tool_name": scores.get("tool_name", ""),
                    "homepage": row.get("homepage", ""),
                    "homepage_status": row.get("homepage_status", ""),
                    "homepage_error": row.get("homepage_error", ""),
                    "publication_ids": publication_ids_str,
                    "include": decision_str,
                    "in_biotools_name": (
                        "" if name_registry_value is None else name_registry_value
                    ),
                    "in_biotools": (
                        "" if in_registry_value is None else in_registry_value
                    ),
                    "bio_score": scores.get("bio_score", ""),
                    "bio_A1": bio_subscores.get("A1", ""),
                    "bio_A2": bio_subscores.get("A2", ""),
                    "bio_A3": bio_subscores.get("A3", ""),
                    "bio_A4": bio_subscores.get("A4", ""),
                    "bio_A5": bio_subscores.get("A5", ""),
                    "documentation_score": scores.get("documentation_score", ""),
                    "confidence_score": scores.get("confidence_score", ""),
                    "doc_B1": doc_subscores.get("B1", ""),
                    "doc_B2": doc_subscores.get("B2", ""),
                    "doc_B3": doc_subscores.get("B3", ""),
                    "doc_B4": doc_subscores.get("B4", ""),
                    "doc_B5": doc_subscores.get("B5", ""),
                    "concise_description": scores.get("concise_description", ""),
                    "rationale": scores.get("rationale", ""),
                    "model": scores.get("model", ""),
                    "origin_types": origin_types_str,
                    "biotools_api_status": row.get("biotools_api_status", ""),
                    "api_name": row.get("api_name", ""),
                    "api_status": row.get("api_status", ""),
                    "api_description": row.get("api_description", ""),
                }
            )


DecisionCategory = Literal["add", "review", "do_not_add"]


def _coerce_unit_score(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result < 0.0:
        return 0.0
    if result > 1.0:
        return 1.0
    return result


def _apply_doc_score_v2(scores: dict[str, Any]) -> float:
    weights = {"B1": 2.0, "B2": 1.0, "B3": 1.0, "B4": 1.0, "B5": 2.0}
    denominator = sum(weights.values())
    documentation_subscores = scores.get("documentation_subscores")
    have_any_subscores = False
    numerator = 0.0

    if isinstance(documentation_subscores, dict):
        for key, weight in weights.items():
            value = _coerce_unit_score(documentation_subscores.get(key))
            numerator += value * weight
            if documentation_subscores.get(key) is not None:
                have_any_subscores = True

    doc_score_v2: float
    if have_any_subscores:
        doc_score_v2 = numerator / denominator
    else:
        doc_score_v2 = _coerce_unit_score(scores.get("documentation_score"))

    existing_score = scores.get("documentation_score")
    if (
        existing_score is not None
        and "documentation_score_raw" not in scores
        and existing_score != doc_score_v2
    ):
        scores["documentation_score_raw"] = existing_score

    scores["doc_score_v2"] = doc_score_v2
    scores["documentation_score"] = doc_score_v2
    return doc_score_v2


def classify_candidate(
    scores: dict[str, Any],
    *,
    bio_thresholds: tuple[float, float],
    doc_thresholds: tuple[float, float],
    has_homepage: bool,
) -> DecisionCategory:
    _apply_doc_score_v2(scores)

    if not has_homepage:
        return "do_not_add"

    bio_score = _coerce_unit_score(scores.get("bio_score"))
    doc_score_v2 = _coerce_unit_score(scores.get("documentation_score"))

    review_bio, add_bio = bio_thresholds
    review_doc, add_doc = doc_thresholds

    bio_add_threshold = add_bio
    bio_review_threshold = review_bio
    doc_add_threshold = add_doc
    doc_review_threshold = review_doc

    documentation_subscores = scores.get("documentation_subscores")
    if not isinstance(documentation_subscores, dict):
        documentation_subscores = {}
    bio_subscores = scores.get("bio_subscores")
    if not isinstance(bio_subscores, dict):
        bio_subscores = {}

    b2 = _coerce_unit_score(documentation_subscores.get("B2"))
    b3 = _coerce_unit_score(documentation_subscores.get("B3"))
    a4 = _coerce_unit_score(bio_subscores.get("A4"))

    has_execution_path = b2 >= 0.5 or a4 >= 0.99
    has_repro_anchor = b3 >= 0.5

    if bio_score >= bio_add_threshold and doc_score_v2 >= doc_add_threshold:
        if has_execution_path and has_repro_anchor:
            return "add"
        return "review"

    if bio_score >= bio_review_threshold and doc_score_v2 >= doc_review_threshold:
        return "review"

    return "do_not_add"


def _parse_status_code(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.match(r"^(\d{3})", text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _homepage_is_usable(
    homepage: str | None,
    status: Any,
    error: Any,
) -> bool:
    if not homepage or not str(homepage).strip():
        return False
    code = _parse_status_code(status)
    if code is not None and code >= 400:
        return False
    if isinstance(error, str) and error.strip():
        return False
    return True


def _apply_documentation_penalty(
    scores: dict[str, Any],
    homepage_ok: bool,
) -> None:
    if homepage_ok:
        return
    scores["documentation_score"] = 0.0
    doc_subscores = scores.get("documentation_subscores")
    if isinstance(doc_subscores, dict):
        for key in ("B1", "B2", "B3", "B4", "B5"):
            if key in doc_subscores:
                doc_subscores[key] = 0.0


def to_entry(
    c: dict[str, Any], homepage: str | None, scores: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build bio.tools payload entry from candidate.

    Preserves the original pub2tools structure (function, topic, link, etc.)
    and updates the description field with LLM-generated content from scores.
    """
    # Start with a deep copy of the candidate to preserve all pub2tools fields
    entry: dict[str, Any] = {}

    # Copy all fields from candidate except those we'll explicitly override
    for key, value in c.items():
        if key not in (
            "title",
            "urls",
            "tags",
            "in_biotools",
            "in_biotools_name",
            "homepage_status",
            "homepage_error",
            "enrichment_context",
            "confidence_flag",  # internal QA hint
        ):
            entry[key] = value

    # Remove internal confidence metadata that bio.tools does not accept
    entry.pop("confidence_flag", None)

    # Ensure required fields are present
    # Prioritize tool_name from scores (assessment.csv), then fall back to candidate data
    name = (
        (scores.get("tool_name") if scores else None)
        or c.get("title")
        or c.get("name")
        or "Unnamed Tool"
    )
    entry["name"] = str(name)

    # Update description with LLM-generated concise_description from scores if available
    # This is the key improvement: use the scoring output description
    if scores and scores.get("concise_description"):
        entry["description"] = scores["concise_description"]
    elif "description" not in entry or not entry["description"]:
        # Fallback to original description or generic message
        entry["description"] = c.get("description") or "Candidate tool from Pub2Tools"

    # Update homepage if provided
    if homepage:
        entry["homepage"] = homepage
    elif "homepage" not in entry:
        entry["homepage"] = ""

    # Ensure biotoolsID is present
    if "biotoolsID" not in entry:
        biotools_id = (
            c.get("biotoolsID")
            or c.get("biotools_id")
            or c.get("id")
            or c.get("tool_id")
            or c.get("identifier")
        )
        if biotools_id:
            entry["biotoolsID"] = str(biotools_id)

    # Filter documentation to only include valid types according to bio.tools schema
    if "documentation" in entry:
        valid_doc_types = {
            "API documentation",
            "Citation instructions",
            "Code of conduct",
            "Command-line options",
            "Contributions policy",
            "FAQ",
            "General",
            "Governance",
            "Installation instructions",
            "Quick start guide",
            "User manual",
            "Release notes",
            "Terms of use",
            "Training material",
            "Other",
        }
        docs = entry["documentation"]
        if isinstance(docs, list):
            filtered_docs = []
            for doc in docs:
                if isinstance(doc, dict) and "type" in doc:
                    # Filter type array to only include valid types
                    if isinstance(doc["type"], list):
                        valid_types = [t for t in doc["type"] if t in valid_doc_types]
                        if valid_types:
                            doc["type"] = valid_types
                            filtered_docs.append(doc)
                    elif doc["type"] in valid_doc_types:
                        filtered_docs.append(doc)
                elif isinstance(doc, dict):
                    # If no type field, skip it (type is required)
                    continue
            if filtered_docs:
                entry["documentation"] = filtered_docs
            else:
                # Remove documentation if no valid entries remain
                del entry["documentation"]
        else:
            # Documentation should be a list, remove if not
            del entry["documentation"]

    return entry


def validate_biotools_payload(
    payload: list[dict[str, Any]],
    logger,
    payload_type: str = "payload",
    use_api: bool = False,
    api_base: str = "https://bio.tools/api/tool/validate/",
    token: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate payload entries against bio.tools schema.

    Args:
        payload: List of tool entries to validate
        logger: Logger instance
        payload_type: Type of payload for logging (e.g., "Add payload", "Review payload")
        use_api: If True, use bio.tools API validation; if False, use local Pydantic validation
        api_base: Base URL for the validation API endpoint
        token: Optional authentication token for dev server access

    Returns:
        (valid_entries, validation_errors)
        - valid_entries: List of entries that passed validation
        - validation_errors: List of dicts with 'name', 'biotoolsID', and 'errors' keys

    """
    from pydantic import ValidationError

    from biotoolsllmannotate.io.biotools_api import validate_biotools_entry

    valid_entries = []
    validation_errors = []

    # Log which validation method is being used
    if use_api:
        if token:
            logger.info(
                f"Validating {payload_type} against bio.tools API ({api_base}) with authentication"
            )
        else:
            logger.info(
                f"Validating {payload_type} against bio.tools API ({api_base}) without token - may fall back to local validation"
            )
    else:
        logger.info(f"Validating {payload_type} using local Pydantic schema")

    for entry in payload:
        entry_name = entry.get("name", "Unknown")
        entry_id = entry.get("biotoolsID", "")

        if use_api:
            # Use bio.tools API validation endpoint
            logger.debug(f"Validating '{entry_name}' against bio.tools API...")
            validation_result = validate_biotools_entry(
                entry, api_base=api_base, token=token
            )

            if validation_result["valid"]:
                valid_entries.append(entry)
            else:
                # Check for authentication errors - fall back to local validation
                errors = validation_result.get("errors", [])
                if any(
                    "401" in str(err) or "Authentication" in str(err) for err in errors
                ):
                    logger.warning(
                        f"bio.tools API requires authentication for '{entry_name}', falling back to local validation"
                    )
                    # Retry with local Pydantic validation
                    try:
                        BioToolsEntry(**entry)
                        valid_entries.append(entry)
                        logger.info(
                            f"  ✓ {entry_name} ({entry_id}): Valid (local Pydantic)"
                        )
                    except ValidationError as e:
                        error_details = []
                        for error in e.errors():
                            field = ".".join(str(loc) for loc in error["loc"])
                            msg = error["msg"]
                            error_details.append(f"{field}: {msg}")
                        validation_errors.append(
                            {
                                "name": entry_name,
                                "biotoolsID": entry_id,
                                "errors": error_details,
                            }
                        )
                else:
                    validation_errors.append(
                        {
                            "name": entry_name,
                            "biotoolsID": entry_id,
                            "errors": validation_result["errors"],
                            "warnings": validation_result.get("warnings", []),
                        }
                    )
                    logger.warning(
                        f"bio.tools API validation failed for '{entry_name}' (ID: {entry_id}): {len(validation_result['errors'])} errors"
                    )
        else:
            # Use local Pydantic validation
            try:
                BioToolsEntry(**entry)
                valid_entries.append(entry)
            except ValidationError as e:
                error_details = []
                for error in e.errors():
                    field = ".".join(str(loc) for loc in error["loc"])
                    msg = error["msg"]
                    error_details.append(f"{field}: {msg}")

                validation_errors.append(
                    {
                        "name": entry_name,
                        "biotoolsID": entry_id,
                        "errors": error_details,
                    }
                )
                logger.warning(
                    f"Local schema validation failed for '{entry_name}' (ID: {entry_id}): {len(error_details)} errors"
                )

    validation_method = "bio.tools API" if use_api else "local Pydantic"
    if validation_errors:
        logger.warning(
            f"❌ {payload_type}: {len(validation_errors)}/{len(payload)} entries failed {validation_method} validation"
        )
    else:
        logger.info(
            f"✅ {payload_type}: All {len(payload)} entries passed {validation_method} validation"
        )

    return valid_entries, validation_errors


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
    for folder in ("exports", "reports", "cache", "logs", "pub2tools", "ollama"):
        (base_path / folder).mkdir(parents=True, exist_ok=True)

    legacy_root = Path("out")
    if base_path.resolve() != legacy_root.resolve():
        return

    migrations = [
        (legacy_root / "payload.json", base_path / "exports" / "biotools_payload.json"),
        (legacy_root / "report.jsonl", base_path / "reports" / "assessment.csv"),
        (legacy_root / "report.csv", base_path / "reports" / "assessment.csv"),
        (
            legacy_root / "updated_entries.json",
            base_path / "exports" / "biotools_entries.json",
        ),
        (
            legacy_root / "enriched_candidates.json.gz",
            base_path / "cache" / "enriched_candidates.json.gz",
        ),
        (
            legacy_root / "ollama.log",
            base_path / "logs" / "ollama" / "ollama.log",
        ),
        (
            legacy_root / "ollama-trace.jsonl",
            base_path / "ollama" / "trace.jsonl",
        ),
        (
            base_path / "logs" / "ollama" / "trace.jsonl",
            base_path / "ollama" / "trace.jsonl",
        ),
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
                base_path / "reports" / "assessment.csv",
            ),
            (
                pipeline / "reports" / "assessment.csv",
                base_path / "reports" / "assessment.csv",
            ),
            (
                pipeline / "cache" / "enriched_candidates.json.gz",
                base_path / "cache" / "enriched_candidates.json.gz",
            ),
            (
                pipeline / "logs" / "ollama.log",
                base_path / "logs" / "ollama" / "ollama.log",
            ),
            (
                pipeline / "logs" / "ollama-trace.jsonl",
                base_path / "ollama" / "trace.jsonl",
            ),
            (
                pipeline / "ollama" / "trace.jsonl",
                base_path / "ollama" / "trace.jsonl",
            ),
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
    # Disabled: no longer write biotools_entries.json or updated entries
    pass


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
        # Skip adding homepage link for dev API compatibility (see above comment).
        pass
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


def _find_latest_pub2tools_export(
    *bases: Path, time_period_label: str | None = None
) -> Path | None:
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

    # If a time period label is provided, prioritize exports that match it
    if time_period_label:
        matching = [
            c
            for c in candidates
            if _export_matches_time_period(c[1], time_period_label)
        ]
        if matching:
            matching.sort(key=lambda item: item[0], reverse=True)
            return matching[0][1]

    # Fall back to latest by modification time
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _export_matches_time_period(path: Path, label: str) -> bool:
    label_prefix = f"{label}_"
    for part in path.parts:
        if part == label or part.startswith(label_prefix):
            return True
    return False


def _load_assessment_report(path: Path) -> list[dict[str, Any]]:
    """Load assessment report from CSV file."""
    csv_path = path.with_suffix(".csv")
    if not csv_path.exists():
        return []
    return _load_assessment_from_csv(csv_path)


def _load_assessment_from_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Load and reconstruct assessment data from CSV file."""
    rows: list[dict[str, Any]] = []

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for csv_row in reader:
            # Parse publication_ids
            pub_ids_str = csv_row.get("publication_ids", "").strip()
            publication_ids = []
            if pub_ids_str:
                publication_ids = [
                    p.strip() for p in pub_ids_str.split(",") if p.strip()
                ]

            # Parse origin_types
            origin_str = csv_row.get("origin_types", "").strip()
            origin_types = []
            if origin_str:
                origin_types = [o.strip() for o in origin_str.split(",") if o.strip()]

            # Helper to convert CSV string to float or None
            def parse_float(val):
                if not val or str(val).strip() == "":
                    return None
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            # Helper to convert CSV string to bool or None
            def parse_bool(val):
                if not val or str(val).strip() == "":
                    return None
                val_lower = str(val).strip().lower()
                if val_lower in ("true", "1", "yes"):
                    return True
                elif val_lower in ("false", "0", "no"):
                    return False
                return None

            # Check for manual override first
            manual_decision = csv_row.get("manual_decision", "").strip()
            if manual_decision:
                # Manual override takes precedence
                decision = manual_decision
            else:
                # Parse decision from include column
                decision_str = csv_row.get("include", "").strip()
                if decision_str == "True":
                    decision = "add"
                elif decision_str == "False":
                    decision = "do_not_add"
                elif decision_str:
                    decision = decision_str
                else:
                    decision = "do_not_add"

            # Reconstruct the bio_subscores
            bio_subscores = {}
            for key in ["A1", "A2", "A3", "A4", "A5"]:
                val = parse_float(csv_row.get(f"bio_{key}"))
                if val is not None:
                    bio_subscores[key] = val

            # Reconstruct the documentation_subscores
            doc_subscores = {}
            for key in ["B1", "B2", "B3", "B4", "B5"]:
                val = parse_float(csv_row.get(f"doc_{key}"))
                if val is not None:
                    doc_subscores[key] = val

            # Reconstruct the scores object
            scores = {}

            # Add scalar scores
            bio_score = parse_float(csv_row.get("bio_score"))
            if bio_score is not None:
                scores["bio_score"] = bio_score

            doc_score = parse_float(csv_row.get("documentation_score"))
            if doc_score is not None:
                scores["documentation_score"] = doc_score

            confidence = parse_float(csv_row.get("confidence_score"))
            if confidence is not None:
                scores["confidence_score"] = confidence

            # Add subscores
            if bio_subscores:
                scores["bio_subscores"] = bio_subscores
            if doc_subscores:
                scores["documentation_subscores"] = doc_subscores

            # Add text fields
            if csv_row.get("tool_name"):
                scores["tool_name"] = csv_row["tool_name"]
            if csv_row.get("concise_description"):
                scores["concise_description"] = csv_row["concise_description"]
            if csv_row.get("rationale"):
                scores["rationale"] = csv_row["rationale"]
            if csv_row.get("model"):
                scores["model"] = csv_row["model"]
            if origin_types:
                scores["origin_types"] = origin_types

            # Parse in_biotools fields (can be bool or None)
            in_biotools_name = parse_bool(csv_row.get("in_biotools_name"))
            in_biotools = parse_bool(csv_row.get("in_biotools"))

            # Reconstruct the row
            row = {
                "id": csv_row.get("id", "").strip(),
                "title": csv_row.get("title", "").strip(),
                "homepage": csv_row.get("homepage", "").strip(),
                "homepage_status": csv_row.get("homepage_status", "").strip() or None,
                "homepage_error": csv_row.get("homepage_error", "").strip() or None,
                "publication_ids": publication_ids,
                "scores": scores,
                "include": decision,
                "decision": decision,
                "manual_decision": manual_decision if manual_decision else None,
                "in_biotools_name": in_biotools_name,
                "in_biotools": in_biotools,
            }

            # Add bio.tools API fields if present
            if csv_row.get("biotools_api_status"):
                row["biotools_api_status"] = csv_row["biotools_api_status"]
            if csv_row.get("api_name"):
                row["api_name"] = csv_row["api_name"]
            if csv_row.get("api_status"):
                row["api_status"] = csv_row["api_status"]
            if csv_row.get("api_description"):
                row["api_description"] = csv_row["api_description"]

            rows.append(row)

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
        if isinstance(source, str):
            stripped = source.strip()
            if not stripped or is_probable_publication_url(stripped):
                continue
            return stripped
    for url in candidate.get("urls") or []:
        url_str = str(url).strip()
        if not url_str:
            continue
        if is_probable_publication_url(url_str):
            continue
        if url_str.startswith("http://") or url_str.startswith("https://"):
            return url_str
    return ""


def upload_biotools_entries(
    add_entries: list[dict[str, Any]],
    output_dir: Path,
    api_base: str = "https://bio.tools/api/tool/",
    retry_attempts: int = 3,
    retry_delay: float = 1.0,
    batch_delay: float = 0.5,
    logger: Any = None,
) -> dict[str, Any]:
    """Upload bio.tools entries to the registry.

    Args:
        add_entries: List of entries to upload from biotools_add.json
        output_dir: Output directory for upload_results.jsonl
        api_base: Bio.tools API base URL
        retry_attempts: Number of retry attempts for transient errors
        retry_delay: Initial delay for exponential backoff
        batch_delay: Delay between entries to avoid rate limits
        logger: Logger instance

    Returns:
        Dict with upload statistics and results

    """
    import json as json_lib
    import time

    if logger is None:
        from biotoolsllmannotate.io.logging import get_logger

        logger = get_logger()

    # Read token
    token = read_biotools_token()
    if not token:
        logger.error(
            "❌ --upload requires .bt_token file. Create .bt_token in repository root with bio.tools API token."
        )
        raise RuntimeError("bio.tools token not found")

    logger.info("✓ Found bio.tools authentication token")

    upload_stats = {"uploaded": 0, "failed": 0, "skipped": 0, "results": []}
    results_file = output_dir / "upload_results.jsonl"

    for idx, entry in enumerate(add_entries):
        biotools_id = entry.get("biotoolsID")
        if not biotools_id:
            logger.warning(
                f"  ⊘ Skipping entry without biotoolsID: {entry.get('name')}"
            )
            upload_stats["skipped"] += 1
            continue

        # Check if entry exists
        try:
            existing = fetch_biotools_entry(biotools_id, api_base, token)
        except Exception as exc:
            logger.warning(f"  ⚠️  Error checking existence of {biotools_id}: {exc}")
            result = {
                "biotools_id": biotools_id,
                "status": "failed",
                "error": f"Check existence failed: {str(exc)}",
                "response_code": 0,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            upload_stats["results"].append(result)
            upload_stats["failed"] += 1
            with open(results_file, "a") as f:
                f.write(json_lib.dumps(result) + "\n")
            continue

        if existing is not None:
            logger.info(f"  ⊘ Skipping {biotools_id} (already exists on bio.tools)")
            result = {
                "biotools_id": biotools_id,
                "status": "skipped",
                "error": "Entry already exists",
                "response_code": 409,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            upload_stats["results"].append(result)
            upload_stats["skipped"] += 1
            with open(results_file, "a") as f:
                f.write(json_lib.dumps(result) + "\n")
            continue

        # Upload new entry
        logger.info(f"  → Uploading {biotools_id}...")
        response = create_biotools_entry(
            entry,
            api_base=api_base,
            token=token,
            retry_attempts=retry_attempts,
            retry_delay=retry_delay,
        )

        if response["success"]:
            logger.info(f"  ✓ Uploaded {biotools_id}")
            upload_stats["uploaded"] += 1
            status = "uploaded"
            error_msg = None
            code = 201
        else:
            logger.warning(f"  ✗ Failed to upload {biotools_id}: {response['error']}")
            upload_stats["failed"] += 1
            status = "failed"
            error_msg = response["error"]
            code = response.get("status_code", 0)

        result = {
            "biotools_id": biotools_id,
            "status": status,
            "error": error_msg,
            "response_code": code,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        upload_stats["results"].append(result)

        # Write result to jsonl log
        with open(results_file, "a") as f:
            f.write(json_lib.dumps(result) + "\n")

        # Apply batch delay to avoid rate limiting
        if idx < len(add_entries) - 1:
            time.sleep(batch_delay)

    # Print summary
    logger.info("")
    logger.info("Upload Summary:")
    logger.info(f"  ✓ Uploaded: {upload_stats['uploaded']} entries")
    logger.info(f"  ✗ Failed: {upload_stats['failed']} entries")
    logger.info(f"  ⊘ Skipped: {upload_stats['skipped']} entries")

    if upload_stats["failed"] > 0:
        logger.info("")
        logger.info("Failed Entries:")
        for result in upload_stats["results"]:
            if result["status"] == "failed":
                logger.info(f"  • {result['biotools_id']}: {result['error']}")

    logger.info(f"Detailed results logged to {results_file}")

    return upload_stats


def write_upload_report_csv(
    upload_stats: dict[str, Any],
    output_dir: Path,
    api_base: str = "https://bio.tools/api/tool/",
    logger: Any = None,
) -> None:
    """Write a CSV report summarizing upload results with bio.tools URLs.

    Args:
        upload_stats: Dict with 'results' list from upload_biotools_entries()
        output_dir: Output directory for the report
        api_base: Base URL for bio.tools API (used to construct tool URLs)
        logger: Logger instance

    """
    if logger is None:
        from biotoolsllmannotate.io.logging import get_logger

        logger = get_logger(__name__)

    report_path = output_dir / "upload_report.csv"
    ensure_parent(report_path)

    fieldnames = [
        "biotoolsID",
        "status",
        "bio_tools_url",
        "error",
        "response_code",
        "timestamp",
    ]

    with report_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for result in upload_stats.get("results", []):
            biotools_id = result.get("biotools_id", "")
            status = result.get("status", "")

            # Construct bio.tools URL for uploaded entries and entries that already exist
            # (failed with duplicate ID error or skipped during pre-flight check)
            if status in ("uploaded", "skipped") or (
                status == "failed"
                and result.get("error", "").find("already exists") != -1
            ):
                bio_tools_url = f"{api_base.rstrip('/')}/{biotools_id}"
            else:
                bio_tools_url = ""

            writer.writerow(
                {
                    "biotoolsID": biotools_id,
                    "status": status,
                    "bio_tools_url": bio_tools_url,
                    "error": result.get("error") or "",
                    "response_code": result.get("response_code", ""),
                    "timestamp": result.get("timestamp", ""),
                }
            )

    logger.info(f"Upload report written to {report_path}")


def execute_run(
    from_date: str | None = None,
    to_date: str | None = None,
    bio_thresholds: tuple[float, float] = (0.5, 0.6),
    doc_thresholds: tuple[float, float] = (0.5, 0.6),
    limit: int | None = None,
    dry_run: bool = False,
    output: Path | None = None,
    report: Path | None = None,
    model: str | None = None,
    concurrency: int = 8,
    custom_pub2tools_biotools_json: str | None = None,
    registry_path: str | None = None,
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
    validate_biotools_api: bool = False,
    biotools_api_base: str = "https://bio.tools/api/tool/",
    biotools_validate_api_base: str = "https://bio.tools/api/tool/validate/",
    upload: bool = False,
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

    bio_review_threshold, bio_add_threshold = bio_thresholds
    doc_review_threshold, doc_add_threshold = doc_thresholds

    bio_review_threshold = max(0.0, min(bio_review_threshold, 1.0))
    bio_add_threshold = max(0.0, min(bio_add_threshold, 1.0))
    doc_review_threshold = max(0.0, min(doc_review_threshold, 1.0))
    doc_add_threshold = max(0.0, min(doc_add_threshold, 1.0))

    if bio_review_threshold > bio_add_threshold:
        bio_review_threshold = bio_add_threshold
    if doc_review_threshold > doc_add_threshold:
        doc_review_threshold = doc_add_threshold

    bio_thresholds = (bio_review_threshold, bio_add_threshold)
    doc_thresholds = (doc_review_threshold, doc_add_threshold)

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

    def _coerce_log_level(raw: Any) -> int | None:
        if raw is None:
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            if text.isdigit():
                try:
                    return int(text)
                except ValueError:
                    return None
            mapped = getattr(logging, text.upper(), None)
            if isinstance(mapped, int):
                return mapped
        return None

    logging_cfg = config_data.get("logging")
    if not isinstance(logging_cfg, dict):
        logging_cfg = {}
    env_level = _coerce_log_level(os.environ.get("BIOTOOLS_LOG_LEVEL"))
    config_level = _coerce_log_level(logging_cfg.get("level"))
    log_level = env_level or config_level or logging.INFO

    setup_logging(level=log_level, console=console)
    logger = get_logger("pipeline")

    registry: BioToolsRegistry | None = None

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

        explicit_input = custom_pub2tools_biotools_json or os.environ.get(
            "BIOTOOLS_ANNOTATE_INPUT"
        )
        explicit_input = explicit_input or os.environ.get("BIOTOOLS_ANNOTATE_JSON")
        has_explicit_input = bool(explicit_input)
        custom_label = "custom_tool_set"
        # Only use custom_tool_set when explicit input is provided (no sticky behavior)
        use_custom_label = has_explicit_input
        if use_custom_label:
            time_period_label = custom_label
        else:
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
            report = base_output_root / "reports" / "assessment.csv"
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
                        # When resuming from scoring, also use the enriched cache to avoid re-scraping/re-enriching
                        if enriched_cache and enriched_cache.exists():
                            logger.info(
                                "Automatically enabling --resume-from-enriched to skip re-enrichment"
                            )
                            resume_from_enriched = True
                    else:
                        logger.warning(
                            "--resume-from-scoring requested but cached assessment %s contained no rows; rerunning scoring",
                            report,
                        )
                        cached_assessment_rows = None
                        # Fall back to enriched cache if available to avoid re-fetching from pub2tools
                        if enriched_cache and enriched_cache.exists():
                            logger.info(
                                "Automatically enabling --resume-from-enriched to use cached candidates"
                            )
                            resume_from_enriched = True
                except Exception as exc:
                    logger.warning(
                        "Failed to read cached assessment %s: %s; rerunning scoring",
                        report,
                        exc,
                    )
                    cached_assessment_rows = None
                    # Fall back to enriched cache if available to avoid re-fetching from pub2tools
                    if enriched_cache and enriched_cache.exists():
                        logger.info(
                            "Automatically enabling --resume-from-enriched to use cached candidates"
                        )
                        resume_from_enriched = True
            else:
                logger.warning(
                    "--resume-from-scoring requested but assessment report not found: %s",
                    report,
                )
                # Fall back to enriched cache if available to avoid re-fetching from pub2tools
                if enriched_cache and enriched_cache.exists():
                    logger.info(
                        "Automatically enabling --resume-from-enriched to use cached candidates"
                    )
                    resume_from_enriched = True

        time_period_root.mkdir(parents=True, exist_ok=True)
        for folder in ("exports", "reports", "cache", "logs", "pub2tools", "ollama"):
            (time_period_root / folder).mkdir(parents=True, exist_ok=True)
        ollama_log_root = time_period_root / "logs" / "ollama"
        ollama_log_root.mkdir(parents=True, exist_ok=True)
        ollama_trace_root = time_period_root / "ollama"
        ollama_trace_root.mkdir(parents=True, exist_ok=True)

        logging_cfg = config_data.get("logging")
        if not isinstance(logging_cfg, dict):
            logging_cfg = {}
            config_data["logging"] = logging_cfg
        llm_log_value = logging_cfg.get("llm_log")
        llm_log_path = (
            _rebase_to_time_period(llm_log_value)
            if llm_log_value is not None
            else ollama_log_root / "ollama.log"
        )
        logging_cfg["llm_log"] = str(llm_log_path)

        llm_trace_value = logging_cfg.get("llm_trace")
        llm_trace_path = (
            _rebase_to_time_period(llm_trace_value)
            if llm_trace_value is not None
            else ollama_trace_root / "trace.jsonl"
        )
        logging_cfg["llm_trace"] = str(llm_trace_path)

        try:
            Path(llm_log_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            Path(llm_trace_path).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

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
            "   🎯 Thresholds → bio(add/review): %s/%s, docs(add/review): %s/%s, Limit: %s",
            f"{bio_add_threshold:.2f}",
            f"{bio_review_threshold:.2f}",
            f"{doc_add_threshold:.2f}",
            f"{doc_review_threshold:.2f}",
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
        resume_export_path: Path | None = None
        env_input: str | None = None

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
            env_input = custom_pub2tools_biotools_json or os.environ.get(
                "BIOTOOLS_ANNOTATE_INPUT"
            )
            if not env_input:
                env_input = os.environ.get("BIOTOOLS_ANNOTATE_JSON")
            if resume_from_pub2tools and not env_input:
                resume_export_path = _find_latest_pub2tools_export(
                    time_period_root / "pub2tools",
                    base_output_root / "pub2tools",
                    time_period_root / "pipeline" / "pub2tools",
                    base_output_root / "pipeline" / "pub2tools",
                    time_period_root,
                    time_period_label=time_period_label,
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
                    "INPUT file %s -> %d candidates", env_input, len(candidates)
                )
                set_status(
                    0,
                    f"GATHER – loaded {len(candidates)} candidates from input",
                )
            else:
                set_status(0, "GATHER – no local input, Pub2Tools may run")
            if not candidates and not offline and not has_explicit_input:
                try:
                    from ..ingest import pub2tools_client as p2t_client

                    logger.info(
                        "FETCH Pub2Tools range %s → %s",
                        fetch_from_dt.date(),
                        (fetch_to_dt.date() if fetch_to_dt else "now"),
                    )
                    set_status(0, "GATHER – invoking Pub2Tools fetch")
                    pub2tools_output_dir = time_period_root / "pub2tools"
                    candidates = p2t_client.fetch_via_cli(
                        fetch_from_dt,
                        to_date=fetch_to_dt,
                        limit=limit,
                        cli_path=p2t_cli,
                        output_dir=pub2tools_output_dir,
                        edam_owl=edam_owl or "http://edamontology.org/EDAM.owl",
                        idf=idf
                        or "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
                        idf_stemmed=idf_stemmed
                        or "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
                    )
                    if candidates:
                        logger.info(
                            "FETCH pub2tools wrote %d candidates to %s",
                            len(candidates),
                            pub2tools_output_dir / "to_biotools.json",
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

        registry_candidates: list[Path] = []
        if registry_path:
            try:
                registry_candidates.append(Path(registry_path))
            except Exception as exc:
                logger.warning("Invalid registry path %s: %s", registry_path, exc)

        registry_search_roots: list[Path] = []
        pub2tools_dir = time_period_root / "pub2tools"
        registry_search_roots.append(pub2tools_dir)
        if resume_export_path is not None:
            registry_search_roots.append(resume_export_path.parent)
        if env_input:
            registry_search_roots.append(Path(env_input).parent)

        registry_candidates.extend(registry_search_roots)

        if registry is None:
            for root in registry_candidates:
                registry = load_registry_from_pub2tools(root, logger=logger)
                if registry:
                    break
        if registry is None and registry_path:
            logger.warning(
                "Requested registry path %s could not be loaded; membership checks disabled",
                registry_path,
            )

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

        if registry:
            registry_name_hits = 0
            registry_exact_hits = 0
            for candidate in candidates:
                name = candidate.get("title") or candidate.get("name")
                homepage_value = candidate.get("homepage")
                if isinstance(homepage_value, str) and is_probable_publication_url(
                    homepage_value
                ):
                    homepage_value = None
                    candidate.pop("homepage", None)
                homepage = homepage_value
                if not homepage:
                    homepage = primary_homepage(candidate.get("urls") or [])
                    if homepage:
                        candidate["homepage"] = homepage
                name_match = registry.contains_name(name)
                homepage_match = registry.contains(name, homepage)
                candidate["in_biotools_name"] = name_match
                candidate["in_biotools"] = homepage_match
                if name_match:
                    registry_name_hits += 1
                if homepage_match:
                    registry_exact_hits += 1
            if candidates:
                logger.info(
                    "REGISTRY name matches: %d/%d; exact homepage matches: %d",
                    registry_name_hits,
                    len(candidates),
                    registry_exact_hits,
                )
        else:
            for candidate in candidates:
                candidate["in_biotools_name"] = None
                candidate["in_biotools"] = None

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

        payload_add: list[dict[str, Any]] = []
        payload_review: list[dict[str, Any]] = []
        report_rows: list[dict[str, Any]] = []
        add_records: list[tuple[dict[str, Any], dict[str, Any], str]] = []

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
        add_count = 0
        review_count = 0
        rejected_count = 0

        if scoring_resumed:
            by_id, by_title = _build_candidate_index(candidates)
            unmatched_report_rows = 0
            for cached_row in cached_assessment_rows or []:
                row = deepcopy(cached_row)
                scores = row.get("scores") or {}
                if not isinstance(scores, dict):
                    scores = {}
                if "confidence_score" not in scores:
                    scores["confidence_score"] = 0.0
                row["scores"] = scores
                homepage = str(row.get("homepage") or "").strip()
                homepage_status = row.get("homepage_status")
                homepage_error = row.get("homepage_error")
                candidate = _match_candidate_from_report(row, by_id, by_title)

                if candidate is not None:
                    urls = [str(u) for u in (candidate.get("urls") or [])]
                    if not homepage:
                        homepage = (
                            candidate.get("homepage") or primary_homepage(urls) or ""
                        )
                    homepage_status = candidate.get("homepage_status", homepage_status)
                    homepage_error = candidate.get("homepage_error", homepage_error)
                homepage_ok = _homepage_is_usable(
                    homepage, homepage_status, homepage_error
                )
                _apply_documentation_penalty(scores, homepage_ok)

                # Check if user provided manual override
                manual_decision = row.get("manual_decision")
                if manual_decision:
                    # Use manual override
                    decision_value = manual_decision
                    logger.debug(
                        f"Using manual_decision='{decision_value}' for {row.get('id')} ({row.get('title')})"
                    )
                else:
                    # Calculate decision from scores
                    decision_value = classify_candidate(
                        scores,
                        bio_thresholds=bio_thresholds,
                        doc_thresholds=doc_thresholds,
                        has_homepage=homepage_ok,
                    )
                    logger.debug(
                        f"Calculated decision='{decision_value}' for {row.get('id')} ({row.get('title')})"
                    )

                row["homepage"] = homepage
                row["homepage_status"] = homepage_status
                row["homepage_error"] = homepage_error
                row["include"] = decision_value
                row["decision"] = decision_value

                if candidate is None:
                    row.setdefault("in_biotools", None)
                    row.setdefault("in_biotools_name", None)
                    unmatched_report_rows += 1
                    report_rows.append(row)
                    continue

                # Generate biotoolsID if missing
                if candidate and not (
                    candidate.get("biotoolsID")
                    or candidate.get("biotools_id")
                    or candidate.get("id")
                ):
                    tool_name = (
                        candidate.get("title")
                        or candidate.get("name")
                        or row.get("title")
                    )
                    if tool_name:
                        generated_id = generate_biotools_id(tool_name)
                        if generated_id:
                            candidate["biotoolsID"] = generated_id
                            row["id"] = generated_id

                row["in_biotools"] = candidate.get("in_biotools")
                row["in_biotools_name"] = candidate.get("in_biotools_name")
                report_rows.append(row)

                if decision_value == "add":
                    logger.debug(
                        f"Adding to payload_add: {row.get('id')} ({row.get('title')}) - decision='{decision_value}' manual='{manual_decision}'"
                    )
                    payload_add.append(to_entry(candidate, homepage, scores))
                    add_records.append((candidate, scores, homepage))
                elif decision_value == "review":
                    payload_review.append(to_entry(candidate, homepage, scores))

            total_scored = len(report_rows)
            add_count = len(payload_add)
            review_count = len(payload_review)
            rejected_count = max(total_scored - add_count - review_count, 0)
            score_duration = 0.0
            if unmatched_report_rows:
                logger.warning(
                    "Resume scoring skipped %d cached assessment rows because no matching enriched candidate was found",
                    unmatched_report_rows,
                )
            logger.info(
                "RESUME scoring reused %d decisions (%d add, %d review, %d do-not-add)",
                total_scored,
                add_count,
                review_count,
                rejected_count,
            )
            set_status(
                3,
                f"SCORE – reused cached assessment ({add_count} add, {review_count} review, {rejected_count} do-not-add)",
                clear_progress=True,
            )
            logger.info("TIMING score_elapsed_seconds=%.3f", score_duration)
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _decision_payload(
                candidate: dict[str, Any],
                scores: dict[str, Any],
                homepage: str,
                homepage_status: Any,
                homepage_error: Any,
                publication_ids: list[str] | None,
                homepage_ok: bool,
            ) -> tuple[dict[str, Any], DecisionCategory]:
                decision_value = classify_candidate(
                    scores,
                    bio_thresholds=bio_thresholds,
                    doc_thresholds=doc_thresholds,
                    has_homepage=homepage_ok,
                )

                # Get or generate biotoolsID
                tool_id = (
                    candidate.get("id")
                    or candidate.get("tool_id")
                    or candidate.get("biotools_id")
                    or candidate.get("biotoolsID")
                    or candidate.get("identifier")
                )

                # If no ID exists, generate one from the tool name
                if not tool_id:
                    tool_name = (
                        candidate.get("title")
                        or candidate.get("name")
                        or candidate.get("tool_title")
                        or candidate.get("display_title")
                    )
                    if tool_name:
                        generated_id = generate_biotools_id(tool_name)
                        if generated_id:
                            tool_id = generated_id
                            # Store in candidate for use in payload
                            candidate["biotoolsID"] = generated_id

                decision_row = {
                    "id": str(tool_id or ""),
                    "title": str(
                        candidate.get("title")
                        or candidate.get("name")
                        or candidate.get("tool_title")
                        or candidate.get("display_title")
                        or ""
                    ),
                    "homepage": homepage,
                    "homepage_status": homepage_status,
                    "homepage_error": homepage_error,
                    "publication_ids": publication_ids or [],
                    "scores": scores,
                    "include": decision_value,
                    "decision": decision_value,
                    "in_biotools": candidate.get("in_biotools"),
                    "in_biotools_name": candidate.get("in_biotools_name"),
                }
                return decision_row, decision_value

            def heuristic_score_one(c: dict[str, Any]):
                homepage, homepage_reason = _resolve_scoring_homepage(c)
                if homepage_reason:
                    zero_scores = _zero_score_payload(
                        c, homepage=homepage, reason=homepage_reason
                    )
                    decision_row, decision_value = _decision_payload(
                        c,
                        zero_scores,
                        homepage,
                        c.get("homepage_status"),
                        c.get("homepage_error"),
                        zero_scores.get("publication_ids", []),
                        False,
                    )
                    return decision_row, c, homepage, decision_value

                publication_ids = _publication_identifiers(c)
                if publication_ids:
                    c.setdefault("publication_ids", publication_ids)
                scores = simple_scores(c)
                scores.setdefault("model", "heuristic")
                homepage_status = c.get("homepage_status")
                homepage_error = c.get("homepage_error")
                homepage_ok = _homepage_is_usable(
                    homepage, homepage_status, homepage_error
                )
                _apply_documentation_penalty(scores, homepage_ok)
                decision_row, decision_value = _decision_payload(
                    c,
                    scores,
                    homepage,
                    homepage_status,
                    homepage_error,
                    publication_ids,
                    homepage_ok,
                )
                return decision_row, c, homepage, decision_value

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

                def score_one(c: dict[str, Any]):
                    return heuristic_score_one(c)

            else:

                def score_one(c: dict[str, Any]):
                    homepage, homepage_reason = _resolve_scoring_homepage(c)
                    if homepage_reason:
                        zero_scores = _zero_score_payload(
                            c, homepage=homepage, reason=homepage_reason
                        )
                        decision_row, decision_value = _decision_payload(
                            c,
                            zero_scores,
                            homepage,
                            c.get("homepage_status"),
                            c.get("homepage_error"),
                            zero_scores.get("publication_ids", []),
                            False,
                        )
                        return decision_row, c, homepage, decision_value

                    publication_ids = _publication_identifiers(c)
                    if publication_ids:
                        c.setdefault("publication_ids", publication_ids)
                    try:
                        scores = scorer.score_candidate(c)
                    except Exception as exc:
                        score_fallbacks["llm"] += 1
                        logger.warning(
                            "LLM scoring failed for '%s': %s. Using heuristic backup; rerun with --offline or check Ollama service.",
                            c.get("title")
                            or c.get("name")
                            or c.get("id")
                            or "<unknown>",
                            exc,
                        )
                        set_status(
                            3, "SCORE – temporary LLM failure, heuristics applied"
                        )
                        return heuristic_score_one(c)
                    homepage_status = c.get("homepage_status")
                    homepage_error = c.get("homepage_error")
                    homepage_ok = _homepage_is_usable(
                        homepage, homepage_status, homepage_error
                    )
                    _apply_documentation_penalty(scores, homepage_ok)
                    decision_row, decision_value = _decision_payload(
                        c,
                        scores,
                        homepage,
                        homepage_status,
                        homepage_error,
                        publication_ids,
                        homepage_ok,
                    )
                    return decision_row, c, homepage, decision_value

            score_start = perf_counter()
            try:
                if total_candidates:
                    update_interval = max(1, total_candidates // 20)
                    processed = 0
                    with ThreadPoolExecutor(max_workers=concurrency) as executor:
                        futures = [executor.submit(score_one, c) for c in candidates]
                        for fut in as_completed(futures):
                            decision_row, cand, homepage, decision_value = fut.result()
                            processed += 1
                            report_rows.append(decision_row)
                            scores = decision_row.get("scores", {})
                            if (
                                scores.get("model")
                                and scores.get("model") != "heuristic"
                            ):
                                summary_name = (
                                    decision_row.get("title")
                                    or decision_row.get("id")
                                    or "<unknown>"
                                )
                                attempts = scores.get("model_params", {}).get(
                                    "attempts"
                                )
                                attempts_display = (
                                    attempts if attempts is not None else "n/a"
                                )
                                bio_score = scores.get("bio_score")
                                doc_score = scores.get("documentation_score")
                                bio_display = (
                                    f"{bio_score:.2f}"
                                    if isinstance(bio_score, (int, float))
                                    else "n/a"
                                )
                                doc_display = (
                                    f"{doc_score:.2f}"
                                    if isinstance(doc_score, (int, float))
                                    else "n/a"
                                )
                                logger.info(
                                    "SCORE LLM summary for '%s': attempts=%s bio=%s doc=%s",
                                    summary_name,
                                    attempts_display,
                                    bio_display,
                                    doc_display,
                                )
                            if decision_value == "add":
                                payload_add.append(to_entry(cand, homepage, scores))
                                add_records.append((cand, scores, homepage))
                            elif decision_value == "review":
                                payload_review.append(to_entry(cand, homepage, scores))
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

            total_scored = len(report_rows)
            add_count = len(payload_add)
            review_count = len(payload_review)
            rejected_count = max(total_scored - add_count - review_count, 0)
            logger.info(
                "SUMMARY score=%d add=%d review=%d do-not-add=%d llm_fallbacks=%d llm_health_fail=%d duration=%.2fs",
                total_scored,
                add_count,
                review_count,
                rejected_count,
                score_fallbacks.get("llm", 0),
                score_fallbacks.get("health", 0),
                score_duration,
            )
            logger.info("TIMING score_elapsed_seconds=%.3f", score_duration)
            set_status(
                3,
                f"SCORE – complete in {score_duration:.1f}s ({add_count} add, {review_count} review, {rejected_count} do-not-add)",
                clear_progress=True,
            )

        # --- bio.tools API validation step ---
        if validate_biotools_api:
            from biotoolsllmannotate.io.biotools_api import (
                fetch_biotools_entry,
                read_biotools_token,
            )

            bt_token = read_biotools_token()
            if bt_token:
                logger.info("Using bio.tools authentication token for API queries")

            logger.info("Validating payload entries against live bio.tools API...")
            for row in report_rows:
                tool_id = row.get("id") or row.get("biotools_id")

                # If no ID exists, try to generate one from the tool name
                if not tool_id:
                    tool_name = row.get("title") or row.get("name")
                    if tool_name:
                        generated_id = generate_biotools_id(tool_name)
                        if generated_id:
                            tool_id = generated_id
                            # Store the generated ID in the row for future use
                            row["id"] = generated_id
                            logger.debug(
                                f"Generated biotoolsID '{generated_id}' from tool name '{tool_name}'"
                            )

                if not tool_id:
                    row["biotools_api_status"] = "no_id"
                    continue

                try:
                    api_entry = fetch_biotools_entry(
                        tool_id, api_base=biotools_api_base, token=bt_token
                    )
                    if api_entry is None:
                        row["biotools_api_status"] = "not_found"
                    else:
                        row["biotools_api_status"] = "ok"
                        # Add prominent details for CSV
                        row["api_name"] = api_entry.get("name", "")
                        row["api_status"] = api_entry.get("status", "")
                        row["api_description"] = api_entry.get("description", "")
                except Exception as exc:
                    row["biotools_api_status"] = f"error: {exc}"
        logger.info(step_msg(5, "OUTPUT – Write reports and bio.tools payload"))
        set_status(4, "OUTPUT – writing reports")
        report_csv = report.with_suffix(".csv")
        logger.info(f"📝 Writing CSV report to {report_csv}")
        write_report_csv(report_csv, report_rows)

        payload_add = [_strip_null_fields(entry) for entry in payload_add]
        payload_review = [_strip_null_fields(entry) for entry in payload_review]

        # Validate payloads against bio.tools schema
        # Validate payloads against bio.tools schema
        # Read authentication token if available
        from biotoolsllmannotate.io.biotools_api import read_biotools_token

        bt_token = read_biotools_token()

        if bt_token:
            logger.info("✓ Found bio.tools authentication token")
        else:
            logger.info(
                "ℹ No .bt_token file found, will use local validation or unauthenticated API"
            )

        # Use API validation if token is available, otherwise fall back to local
        use_api_validation = validate_biotools_api and bt_token is not None

        payload_add_valid, add_errors = validate_biotools_payload(
            payload_add,
            logger,
            "Add payload",
            use_api=use_api_validation,
            api_base=biotools_validate_api_base,
            token=bt_token,
        )
        payload_review_valid, review_errors = validate_biotools_payload(
            payload_review,
            logger,
            "Review payload",
            use_api=use_api_validation,
            api_base=biotools_validate_api_base,
            token=bt_token,
        )
        if add_errors or review_errors:
            validation_report = output.parent / "schema_validation_errors.jsonl"
            logger.info(f"📝 Writing schema validation errors to {validation_report}")
            with validation_report.open("w", encoding="utf-8") as f:
                for error in add_errors:
                    error["payload_type"] = "add"
                    f.write(json.dumps(error) + "\n")
                for error in review_errors:
                    error["payload_type"] = "review"
                    f.write(json.dumps(error) + "\n")

        if not dry_run:
            if "payload" in output.stem:
                review_stem = output.stem.replace("payload", "review_payload")
            else:
                review_stem = f"{output.stem}_review"
            output_review = output.with_name(f"{review_stem}{output.suffix}")

            # Write invalid entries to biotools_invalid.json
            invalid_path = output.with_name("biotools_invalid.json")
            invalid_entries = []
            for error in add_errors + review_errors:
                # Find the original entry by biotoolsID or name
                entry_id = error.get("biotoolsID")
                entry_name = error.get("name")
                # Try to find the entry in the original payloads
                entry = next(
                    (
                        e
                        for e in payload_add + payload_review
                        if e.get("biotoolsID") == entry_id
                        or e.get("name") == entry_name
                    ),
                    None,
                )
                if entry:
                    invalid_entries.append(
                        {
                            **entry,
                            "errors": error.get("errors", []),
                            "warnings": error.get("warnings", []),
                            "payload_type": error.get("payload_type"),
                        }
                    )
                else:
                    invalid_entries.append(error)
            write_invalid_json(invalid_path, invalid_entries)

            logger.info(
                f"OUTPUT add payload -> {output} ({len(payload_add_valid)}/{len(payload_add)} valid)"
            )
            set_status(4, "OUTPUT – writing payloads")
            write_json(output, payload_add_valid)
            logger.info(
                f"OUTPUT review payload -> {output_review} ({len(payload_review_valid)}/{len(payload_review)} valid)"
            )
            write_json(output_review, payload_review_valid)

            updated_path = updated_entries or output.with_name("biotools_entries.json")
            write_updated_entries(
                add_records,
                updated_path,
                config_data=config_data,
                logger=logger,
            )

            # Upload to bio.tools if requested (CLI flag OR config setting)
            upload_config = config_data.get("pipeline", {}).get("upload", {})
            upload_enabled = upload or upload_config.get("enabled", False)
            logger.info(f"DEBUG: upload flag={upload}, config enabled={upload_config.get('enabled', False)}, upload_enabled={upload_enabled}, payload_add_valid={len(payload_add_valid) if payload_add_valid else 0} entries")
            if upload_enabled and payload_add_valid:
                logger.info("")
                logger.info("Starting bio.tools upload phase...")
                set_status(4, "OUTPUT – uploading to bio.tools")
                try:
                    upload_stats = upload_biotools_entries(
                        add_entries=payload_add_valid,
                        output_dir=output.parent,
                        api_base=biotools_api_base,
                        retry_attempts=upload_config.get("retry_attempts", 3),
                        retry_delay=upload_config.get("retry_delay", 1.0),
                        batch_delay=upload_config.get("batch_delay", 0.5),
                        logger=logger,
                    )
                    # Generate upload report CSV with bio.tools URLs
                    write_upload_report_csv(
                        upload_stats,
                        output_dir=output.parent,
                        api_base=biotools_api_base,
                        logger=logger,
                    )
                except Exception as exc:
                    logger.error(f"❌ Upload failed: {exc}")
                    raise
        else:
            set_status(4, "OUTPUT – dry-run (payloads skipped)")

        logger.info("🎉 Pipeline run complete!")
        set_status(4, "OUTPUT – complete")
    finally:
        if status_board:
            status_board.stop()
    return
