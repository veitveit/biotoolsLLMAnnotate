import re
from typing import Any


def normalize_text(text: str) -> str:
    """Normalize text for deduplication (lowercase, strip, collapse spaces)."""
    return re.sub(r"\s+", " ", text.strip().lower())


def deduplicate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate tool candidates by normalized title and homepage URL.
    Returns a list of unique candidates.
    """
    seen = set()
    unique = []
    for cand in candidates:
        title = normalize_text(cand.get("title") or cand.get("name") or "")
        homepage = normalize_text(cand.get("homepage") or "")
        key = (title, homepage)
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    return unique
