import logging
import re
from collections.abc import Iterable
from typing import Any, Callable, Dict

import requests
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

BASE_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
BASE_FULLTEXT_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
)

_SEARCH_CACHE: Dict[str, Dict[str, Any]] = {}
_FULLTEXT_CACHE: Dict[str, str] = {}
_DEFAULT_REQUESTS_GET = requests.get


def _truncate_for_log(value: str, max_length: int = 80) -> str:
    """Collapse whitespace and trim overly long log fragments."""

    text = " ".join(str(value).strip().split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def _count_documentation_entries(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if value:
        return 1
    return 0


def _homepage_summary(candidate: dict[str, Any]) -> str:
    error = candidate.get("homepage_error")
    if isinstance(error, str) and error.strip():
        return f"error={_truncate_for_log(error)}"

    status = candidate.get("homepage_status")
    if status is not None:
        parts: list[str] = [f"status={status}"]
        docs_count = _count_documentation_entries(candidate.get("documentation"))
        if docs_count:
            parts.append(f"docs={docs_count}")
        if candidate.get("repository"):
            parts.append("repo=yes")
        return ", ".join(parts)

    if candidate.get("homepage_scraped"):
        return "scraped"

    return "not-scraped"


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
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """Augment candidates with publication abstracts and full text from Europe PMC."""

    if offline or not config.get("enabled", True):
        return

    http = session or requests

    if not isinstance(candidates, list):
        candidates = list(candidates)

    total_candidates = len(candidates)
    record_hits = 0
    candidates_enriched = 0
    abstract_enriched = 0
    full_text_enriched = 0
    search_requests = 0
    search_cache_hits = 0
    fulltext_requests = 0
    fulltext_cache_hits = 0

    use_internal_progress = progress_callback is None
    progress: Progress | None = None
    task_id: int | None = None
    if logger and candidates:
        logger.info(
            "🔎 Fetching publication metadata from Europe PMC for %d candidates",
            len(candidates),
        )
    if use_internal_progress and logger and candidates:
        try:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                transient=True,
            )
            progress.start()
            task_id = progress.add_task("Europe PMC", total=len(candidates))
        except Exception:
            progress = None
    timeout = config.get("timeout", 15)
    include_full_text = config.get("include_full_text", False)
    max_full_text_chars = config.get("max_full_text_chars", 4000)
    max_publications = max(1, int(config.get("max_publications", 1)))

    if progress_callback and total_candidates:
        try:
            progress_callback(0, total_candidates)
        except Exception:
            pass

    processed = 0

    for candidate in candidates:
        publications = _extract_publications(candidate)
        if not publications:
            if progress and task_id is not None:
                progress.update(task_id, advance=1)
            if progress_callback and total_candidates:
                processed += 1
                try:
                    progress_callback(processed, total_candidates)
                except Exception:
                    pass
            continue

        candidate_name = (
            candidate.get("title")
            or candidate.get("name")
            or candidate.get("tool_title")
            or candidate.get("display_title")
            or "<unknown>"
        )
        candidate_has_hit = False
        candidate_added_abstract = False
        candidate_added_full_text = False
        used_search_cache = False
        used_fulltext_cache = False

        considered_publications = publications[:max_publications]

        abstracts: list[str] = []
        full_texts: list[str] = []
        full_text_urls: list[str] = []
        collected_ids: list[str] = list(
            p for p in candidate.get("publication_ids", []) if isinstance(p, str)
        )
        seen_ids: set[str] = {p for p in collected_ids}

        for pub in considered_publications:
            identifiers = _select_identifiers(pub)
            if not identifiers:
                continue

            record = None
            record_from_cache = False
            for identifier, id_type in identifiers:
                fetched_record, from_cache, request_count = _fetch_record(
                    identifier,
                    id_type,
                    timeout=timeout,
                    http=http,
                    logger=logger,
                )
                search_requests += request_count
                if from_cache:
                    search_cache_hits += 1
                if fetched_record:
                    record = fetched_record
                    record_from_cache = from_cache
                    break
            if not record:
                if logger:
                    logger.debug(
                        "Europe PMC: no record for identifiers %s on '%s'",
                        [f"{kind}:{value}" for value, kind in identifiers],
                        candidate_name,
                    )
                continue

            record_hits += 1
            candidate_has_hit = True
            used_search_cache = used_search_cache or record_from_cache
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
                candidate_added_abstract = True

            if include_full_text:
                pmcid = record.get("pmcid") or candidate_pmcid
                full_text = None
                if pmcid:
                    full_text, ft_from_cache, ft_requests = _fetch_full_text(
                        pmcid,
                        timeout=timeout,
                        http=http,
                        max_len=max_full_text_chars,
                        logger=logger,
                    )
                    fulltext_requests += ft_requests
                    if ft_from_cache:
                        fulltext_cache_hits += 1
                        used_fulltext_cache = True
                if full_text:
                    full_texts.append(full_text)
                    candidate_added_full_text = True
                else:
                    full_text_urls.extend(record.get("full_text_urls", []))

        if abstracts:
            candidate["publication_abstract"] = "\n\n".join(
                _dedupe_preserve_order(abstracts)
            )
        if full_texts:
            candidate["publication_full_text"] = "\n\n".join(
                _dedupe_preserve_order(full_texts)
            )
        elif (
            include_full_text
            and full_text_urls
            and not candidate.get("publication_full_text")
        ):
            candidate["publication_full_text_url"] = full_text_urls[0]

        if collected_ids:
            candidate["publication_ids"] = _dedupe_preserve_order(collected_ids)

        if candidate_has_hit:
            candidates_enriched += 1
            if candidate_added_abstract:
                abstract_enriched += 1
            if candidate_added_full_text:
                full_text_enriched += 1
            if logger:
                cache_note_parts = []
                if used_search_cache:
                    cache_note_parts.append("search")
                if used_fulltext_cache:
                    cache_note_parts.append("fulltext")
                cache_note = (
                    ", ".join(cache_note_parts) if cache_note_parts else "network"
                )
                homepage_note = _homepage_summary(candidate)
                logger.info(
                    "Europe PMC enriched '%s': abstracts=%d full_texts=%d ids=%d (cache: %s, homepage: %s)",
                    candidate_name,
                    len(abstracts),
                    len(full_texts),
                    len(collected_ids),
                    cache_note,
                    homepage_note,
                )
        elif logger:
            logger.debug(
                "Europe PMC: no enrichment for '%s' (publications inspected: %d)",
                candidate_name,
                len(considered_publications),
            )

        if progress and task_id is not None:
            progress.update(task_id, advance=1)
        if progress_callback and total_candidates:
            processed += 1
            try:
                progress_callback(processed, total_candidates)
            except Exception:
                pass

    if progress:
        progress.stop()

    if progress_callback and total_candidates and processed < total_candidates:
        try:
            progress_callback(total_candidates, total_candidates)
        except Exception:
            pass

    if logger and total_candidates:
        logger.info(
            "Europe PMC summary: candidates=%d records=%d enriched=%d abstracts=%d full_texts=%d search_calls=%d cache_hits=%d fulltext_calls=%d fulltext_cache=%d",
            total_candidates,
            record_hits,
            candidates_enriched,
            abstract_enriched,
            full_text_enriched,
            search_requests,
            search_cache_hits,
            fulltext_requests,
            fulltext_cache_hits,
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
) -> tuple[dict[str, Any] | None, bool, int]:
    cache_key = f"{id_type or 'ext'}:{identifier}".lower()
    if cache_key in _SEARCH_CACHE and _use_cached_response(http):
        if logger:
            logger.debug("Europe PMC search cache hit for %s", cache_key)
        return _SEARCH_CACHE[cache_key], True, 0

    queries: list[tuple[str, str]] = []
    if id_type:
        normalized = id_type.upper()
        value = identifier.upper() if normalized == "PMCID" else identifier
        queries.append((normalized, value))
    queries.append(("EXT_ID", identifier))

    data = None
    requests_made = 0
    for field, value in queries:
        params = {
            "query": f"{field}:{value}",
            "format": "json",
            "resulttype": "core",
            "pageSize": 1,
        }
        try:
            if logger:
                logger.debug("Europe PMC requesting %s:%s", field, value)
            requests_made += 1
            response = http.get(BASE_SEARCH_URL, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            result = (data.get("resultList") or {}).get("result") or []
            if result:
                if logger:
                    logger.debug(
                        "Europe PMC %s:%s returned %d result(s)",
                        field,
                        value,
                        len(result),
                    )
                break
        except Exception as exc:
            if logger:
                logger.debug(
                    "Europe PMC query failed for %s:%s (%s)", field, value, exc
                )
            data = None
    if not data:
        return None, False, requests_made

    result = (data.get("resultList") or {}).get("result") or []
    if not result:
        if logger:
            logger.debug("Europe PMC returned no results for %s", cache_key)
        return None, False, requests_made
    first = result[0]
    record = {
        "title": first.get("title"),
        "abstract": first.get("abstractText"),
        "pmcid": first.get("pmcid"),
        "pmid": first.get("pmid"),
        "full_text_urls": _collect_full_text_urls(first.get("fullTextUrlList")),
    }
    _SEARCH_CACHE[cache_key] = record
    return record, False, requests_made


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
    pmcid: str,
    *,
    timeout: int,
    http: Any,
    max_len: int,
    logger: logging.Logger | None = None,
) -> tuple[str | None, bool, int]:
    cache_key = pmcid.upper()
    if cache_key in _FULLTEXT_CACHE and _use_cached_response(http):
        if logger:
            logger.debug("Europe PMC full-text cache hit for %s", cache_key)
        return _FULLTEXT_CACHE[cache_key], True, 0

    url = BASE_FULLTEXT_URL.format(pmcid=cache_key)
    requests_made = 0
    try:
        if logger:
            logger.debug("Europe PMC requesting full-text for %s", cache_key)
        requests_made += 1
        response = http.get(url, timeout=timeout)
        response.raise_for_status()
        xml_text = response.text
    except Exception as exc:
        if logger:
            logger.debug(
                "Europe PMC full-text request failed for %s: %s", cache_key, exc
            )
        return None, False, requests_made

    text = _xml_to_text(xml_text)
    if not text:
        if logger:
            logger.debug("Europe PMC full-text XML empty for %s", cache_key)
        return None, False, requests_made
    cleaned = _normalize_whitespace(text)[:max_len].strip()
    if cleaned:
        _FULLTEXT_CACHE[cache_key] = cleaned
        if logger:
            logger.debug(
                "Europe PMC full-text stored for %s (%d chars)", cache_key, len(cleaned)
            )
    return cleaned or None, False, requests_made


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


def _use_cached_response(http: Any) -> bool:
    if http is requests:
        return requests.get is _DEFAULT_REQUESTS_GET
    return True
