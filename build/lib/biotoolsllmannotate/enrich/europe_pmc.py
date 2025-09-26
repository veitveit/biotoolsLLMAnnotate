import logging
import re
from collections.abc import Iterable
from typing import Any, Dict

import requests

BASE_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
BASE_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"

_SEARCH_CACHE: Dict[str, Dict[str, Any]] = {}
_FULLTEXT_CACHE: Dict[str, str] = {}


def reset_europe_pmc_cache() -> None:
    """Clear cached Europe PMC responses (useful for tests)."""

    _SEARCH_CACHE.clear()
    _FULLTEXT_CACHE.clear()


def enrich_candidates_with_europe_pmc(
    candidates: Iterable[dict[str, Any]],
    *,
    config: dict[str, Any],
    logger: logging.Logger | None = None,
    offline: bool = False,
    session: Any | None = None,
) -> None:
    """Augment candidates with publication abstracts and full text from Europe PMC."""

    if offline or not config.get("enabled", True):
        return

    http = session or requests
    timeout = config.get("timeout", 15)
    include_full_text = config.get("include_full_text", False)
    max_full_text_chars = config.get("max_full_text_chars", 4000)
    max_publications = max(1, int(config.get("max_publications", 1)))

    for candidate in candidates:
        publications = _extract_publications(candidate)
        if not publications:
            continue

        abstracts: list[str] = []
        full_texts: list[str] = []
        full_text_urls: list[str] = []
        collected_ids: list[str] = list(
            p for p in candidate.get("publication_ids", []) if isinstance(p, str)
        )
        seen_ids: set[str] = {p for p in collected_ids}

        for pub in publications[:max_publications]:
            identifiers = _select_identifiers(pub)
            if not identifiers:
                continue

            record = None
            for identifier, id_type in identifiers:
                record = _fetch_record(
                    identifier,
                    id_type,
                    timeout=timeout,
                    http=http,
                    logger=logger,
                )
                if record:
                    break
            if not record:
                continue

            _collect_identifier_strings(record, collected_ids, seen_ids)
            candidate_pmcid = next(
                (value for value, kind in identifiers if kind == "pmcid"),
                None,
            )
            if candidate_pmcid:
                _collect_identifier_strings(
                    {"pmcid": candidate_pmcid}, collected_ids, seen_ids
                )

            abstract = record.get("abstract")
            if abstract:
                abstracts.append(abstract)

            if include_full_text:
                pmcid = record.get("pmcid") or candidate_pmcid
                full_text = None
                if pmcid:
                    full_text = _fetch_full_text(
                        pmcid,
                        timeout=timeout,
                        http=http,
                        max_len=max_full_text_chars,
                    )
                if full_text:
                    full_texts.append(full_text)
                else:
                    full_text_urls.extend(record.get("full_text_urls", []))

        if abstracts:
            candidate["publication_abstract"] = "\n\n".join(_dedupe_preserve_order(abstracts))
        if full_texts:
            candidate["publication_full_text"] = "\n\n".join(
                _dedupe_preserve_order(full_texts)
            )
        elif include_full_text and full_text_urls and not candidate.get(
            "publication_full_text"
        ):
            candidate["publication_full_text_url"] = full_text_urls[0]

        if collected_ids:
            candidate["publication_ids"] = _dedupe_preserve_order(collected_ids)

        if logger and (abstracts or full_texts):
            logger.debug(
                "Europe PMC enrichment added data for candidate '%s'",
                candidate.get("title") or candidate.get("name") or "<unknown>",
            )


def _extract_publications(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    pubs = candidate.get("publication") or candidate.get("publications") or []
    if isinstance(pubs, dict):
        return [pubs]
    return [p for p in pubs if isinstance(p, dict)]


def _select_identifiers(publication: dict[str, Any]) -> list[tuple[str, str]]:
    lower = {str(k).lower(): v for k, v in publication.items()}
    identifiers: list[tuple[str, str]] = []

    pmcid = lower.get("pmcid") or lower.get("pmc_id")
    if isinstance(pmcid, str) and pmcid.strip():
        identifiers.append((pmcid.strip(), "pmcid"))

    pmid = lower.get("pmid") or lower.get("pm")
    if isinstance(pmid, str) and pmid.strip():
        identifiers.append((pmid.strip(), "pmid"))

    doi = lower.get("doi")
    if isinstance(doi, str) and doi.strip():
        identifiers.append((doi.strip(), "doi"))

    return identifiers


def _fetch_record(
    identifier: str,
    id_type: str | None,
    *,
    timeout: int,
    http: Any,
    logger: logging.Logger | None = None,
) -> dict[str, Any] | None:
    cache_key = f"{id_type or 'ext'}:{identifier}".lower()
    if cache_key in _SEARCH_CACHE:
        return _SEARCH_CACHE[cache_key]

    queries: list[tuple[str, str]] = []
    if id_type:
        normalized = id_type.upper()
        value = identifier.upper() if normalized == "PMCID" else identifier
        queries.append((normalized, value))
    queries.append(("EXT_ID", identifier))

    data = None
    for field, value in queries:
        params = {
            "query": f"{field}:{value}",
            "format": "json",
            "resulttype": "core",
            "pageSize": 1,
        }
        try:
            response = http.get(BASE_SEARCH_URL, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            result = (data.get("resultList") or {}).get("result") or []
            if result:
                break
        except Exception as exc:
            if logger:
                logger.debug(
                    "Europe PMC query failed for %s:%s (%s)", field, value, exc
                )
            data = None
    if not data:
        return None

    result = (data.get("resultList") or {}).get("result") or []
    if not result:
        return None
    first = result[0]
    record = {
        "title": first.get("title"),
        "abstract": first.get("abstractText"),
        "pmcid": first.get("pmcid"),
        "pmid": first.get("pmid"),
        "full_text_urls": _collect_full_text_urls(first.get("fullTextUrlList")),
    }
    _SEARCH_CACHE[cache_key] = record
    return record


def _collect_full_text_urls(full_text_block: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(full_text_block, dict):
        entries = full_text_block.get("fullTextUrl")
        if isinstance(entries, list):
            for entry in entries:
                url = entry.get("url") if isinstance(entry, dict) else None
                if isinstance(url, str) and url:
                    urls.append(url)
    return urls


def _collect_identifier_strings(
    record: dict[str, Any], collected: list[str], seen: set[str]
) -> None:
    for key, prefix in (("pmcid", "pmcid"), ("pmid", "pmid"), ("doi", "doi")):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            normalized = f"{prefix}:{value.strip()}"
            if normalized not in seen:
                collected.append(normalized)
                seen.add(normalized)


def _fetch_full_text(
    pmcid: str, *, timeout: int, http: Any, max_len: int
) -> str | None:
    cache_key = pmcid.upper()
    if cache_key in _FULLTEXT_CACHE:
        return _FULLTEXT_CACHE[cache_key]

    url = BASE_FULLTEXT_URL.format(pmcid=cache_key)
    try:
        response = http.get(url, timeout=timeout)
        response.raise_for_status()
        xml_text = response.text
    except Exception:
        return None

    text = _xml_to_text(xml_text)
    if not text:
        return None
    cleaned = _normalize_whitespace(text)[:max_len].strip()
    if cleaned:
        _FULLTEXT_CACHE[cache_key] = cleaned
    return cleaned or None


def _xml_to_text(xml_text: str) -> str:
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
        return "".join(root.itertext())
    except Exception:
        return ""


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered
