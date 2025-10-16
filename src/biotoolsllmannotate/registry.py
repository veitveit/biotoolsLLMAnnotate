from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from .ingest.dedup import normalize_text

_NAME_KEYS: tuple[str, ...] = (
    "name",
    "toolname",
    "title",
    "biotoolsID",
    "biotools_id",
    "label",
)
_SYNONYM_KEYS: tuple[str, ...] = ("synonym", "synonyms", "alias", "aliases")


def _normalize_homepage(url: str | None) -> str:
    if not url:
        return ""
    trimmed = url.strip()
    if not trimmed:
        return ""
    parsed = urlparse(trimmed)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if not netloc:
        # Handle URLs without scheme by parsing manually (e.g., example.org/path)
        if "://" not in trimmed:
            # Prepend scheme to help urlparse and retry once
            return _normalize_homepage("http://" + trimmed)
        netloc = parsed.path.lower().rstrip("/")
        path = ""
    normalized_path = re.sub(r"/+", "/", path)
    normalized = f"{netloc}{normalized_path}"
    if not normalized:
        return ""
    return normalized


def _extract_names(entry: dict[str, Any]) -> Iterable[str]:
    for key in _NAME_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            yield value
    for key in _SYNONYM_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            yield value
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            for item in value:
                if isinstance(item, str) and item.strip():
                    yield item


def _extract_homepages(entry: dict[str, Any]) -> Iterable[str]:
    homepage = entry.get("homepage")
    if isinstance(homepage, str) and homepage.strip():
        yield homepage
    elif isinstance(homepage, Iterable) and not isinstance(homepage, (str, bytes)):
        for item in homepage:
            if isinstance(item, str) and item.strip():
                yield item

    links = entry.get("link") or entry.get("links")
    if isinstance(links, Iterable) and not isinstance(links, (str, bytes)):
        for value in links:
            if not isinstance(value, dict):
                continue
            link_url = value.get("url") or value.get("uri")
            if not isinstance(link_url, str) or not link_url.strip():
                continue
            types = value.get("type")
            if not types:
                yield link_url
                continue
            if isinstance(types, str):
                types_iter = [types]
            elif isinstance(types, Iterable):
                types_iter = [str(t) for t in types if isinstance(t, (str, bytes))]
            else:
                types_iter = []
            lowered = {t.lower() for t in types_iter}
            if ("homepage" in lowered) or ("home" in lowered):
                yield link_url


@dataclass
class RegistryMatch:
    name: str
    homepage: str
    source_id: Optional[str] = None


class BioToolsRegistry:
    """In-memory lookup table for bio.tools entries."""

    def __init__(self, source_path: Path):
        self.source_path = source_path
        self._names_by_homepage: dict[str, set[str]] = {}
        self._homepages_by_name: dict[str, set[str]] = {}
        self._all_names: set[str] = set()
        self._id_by_homepage_and_name: dict[tuple[str, str], str] = {}
        self._entry_count = 0

    @property
    def entry_count(self) -> int:
        return self._entry_count

    def add_entry(self, entry: dict[str, Any]) -> None:
        names = {normalize_text(n) for n in _extract_names(entry) if normalize_text(n)}
        if not names:
            return
        self._all_names.update(names)
        homepages = {
            _normalize_homepage(h)
            for h in _extract_homepages(entry)
            if _normalize_homepage(h)
        }
        if not homepages:
            return
        biotools_id = None
        for key in ("biotoolsID", "biotools_id", "biotoolsCURIE"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                biotools_id = value.strip()
                break
        for homepage in homepages:
            name_set = self._names_by_homepage.setdefault(homepage, set())
            for name in names:
                name_set.add(name)
                homes = self._homepages_by_name.setdefault(name, set())
                homes.add(homepage)
                if biotools_id:
                    self._id_by_homepage_and_name[(homepage, name)] = biotools_id
        self._entry_count += 1

    def contains_name(self, name: str | None) -> bool:
        if not name:
            return False
        normalized_name = normalize_text(name)
        if not normalized_name:
            return False
        return normalized_name in self._all_names

    def contains(self, name: str | None, homepage: str | None) -> bool:
        match = self.lookup(name=name, homepage=homepage)
        return match is not None

    def lookup(self, name: str | None, homepage: str | None) -> Optional[RegistryMatch]:
        if not name or not homepage:
            return None
        normalized_name = normalize_text(name)
        normalized_homepage = _normalize_homepage(homepage)
        if not normalized_name or not normalized_homepage:
            return None
        candidate_homepages = self._homepages_by_name.get(normalized_name)
        if not candidate_homepages or normalized_homepage not in candidate_homepages:
            return None
        source_id = self._id_by_homepage_and_name.get(
            (normalized_homepage, normalized_name)
        )
        return RegistryMatch(
            name=normalized_name,
            homepage=normalized_homepage,
            source_id=source_id,
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "BioToolsRegistry":
        source_path = Path(path)
        registry = cls(source_path=source_path)
        with source_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        entries: Iterable[dict[str, Any]]
        if isinstance(data, list):
            entries = (entry for entry in data if isinstance(entry, dict))
        elif isinstance(data, dict):
            if isinstance(data.get("entries"), list):
                entries = (
                    entry
                    for entry in data.get("entries", [])
                    if isinstance(entry, dict)
                )
            elif isinstance(data.get("list"), list):
                entries = (
                    entry for entry in data.get("list", []) if isinstance(entry, dict)
                )
            else:
                entries = (entry for entry in data.values() if isinstance(entry, dict))
        else:
            entries = []
        for entry in entries:
            try:
                registry.add_entry(entry)
            except Exception:
                continue
        return registry


def load_registry_from_pub2tools(
    pub2tools_path: Path | str | None,
    *,
    logger: logging.Logger | None = None,
) -> BioToolsRegistry | None:
    if not pub2tools_path:
        return None

    base = Path(pub2tools_path)
    candidate_file: Path | None

    if base.is_file():
        candidate_file = base
    else:
        candidate_file = None
        for filename in ("biotools.json", "biotools_entries.json"):
            potential = base / filename
            if potential.exists():
                candidate_file = potential
                break

    if not candidate_file or not candidate_file.exists():
        if logger:
            logger.debug(
                "No bio.tools registry snapshot detected under %s; membership checks disabled",
                base,
            )
        return None

    try:
        registry = BioToolsRegistry.from_json(candidate_file)
    except Exception as exc:  # pragma: no cover - defensive
        if logger:
            logger.warning(
                "Failed to load bio.tools registry from %s: %s",
                candidate_file,
                exc,
            )
        return None

    if logger:
        logger.info(
            "Loaded bio.tools registry snapshot (%d entries) from %s",
            registry.entry_count,
            candidate_file,
        )
    return registry
