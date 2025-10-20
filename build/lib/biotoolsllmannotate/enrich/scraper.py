from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Iterable
from itertools import islice
from typing import Any

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from requests import exceptions as requests_exc
from urllib.parse import urljoin, urlparse

from ..version import __version__

DEFAULT_USER_AGENT = f"biotoolsllmannotate/{__version__} (+https://github.com/ELIXIR-Belgium/biotoolsLLMAnnotate)"

DEFAULT_MAX_BYTES = 2_000_000  # 2 MB
DEFAULT_MAX_FRAME_FETCHES = 5
DEFAULT_MAX_FRAME_DEPTH = 2

_NUMERIC_STATUS_PATTERN = re.compile(r"^\s*(-?\d+)\s*$")


class ContentTooLargeError(Exception):
    """Raised when a fetched asset exceeds configured guardrails."""


class NonHtmlContentError(Exception):
    """Raised when the fetched asset is not HTML or text."""


def _truncate_error(message: str, limit: int = 140) -> str:
    clean = message.strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _classify_homepage_exception(exc: Exception) -> tuple[str, str]:
    """Return a status label and concise error message for a requests failure."""

    if isinstance(exc, requests_exc.Timeout):
        return "timeout", "request timed out"
    if isinstance(exc, requests_exc.ConnectionError):
        return "connection_error", _truncate_error(str(exc))
    if isinstance(exc, requests_exc.TooManyRedirects):
        return "redirect_error", "too many redirects"
    if isinstance(exc, requests_exc.InvalidURL):
        return "invalid_url", _truncate_error(str(exc))
    if isinstance(exc, requests_exc.SSLError):
        return "ssl_error", _truncate_error(str(exc))
    return "request_error", _truncate_error(str(exc))


def _ensure_textual_response(response: requests.Response) -> None:
    content_type = response.headers.get("Content-Type", "")
    if (
        content_type
        and "html" not in content_type.lower()
        and "text" not in content_type.lower()
    ):
        raise NonHtmlContentError(f"unsupported content-type: {content_type}")


def _materialize_content(response: requests.Response, *, max_bytes: int) -> bytes:
    header_size = response.headers.get("Content-Length")
    if header_size:
        try:
            declared = int(header_size)
        except (TypeError, ValueError):
            declared = None
        else:
            if declared > max_bytes:
                raise ContentTooLargeError(
                    f"declared content length {declared} bytes exceeds limit {max_bytes}"
                )

    content = response.content
    if len(content) > max_bytes:
        raise ContentTooLargeError(
            f"downloaded content length {len(content)} bytes exceeds limit {max_bytes}"
        )
    return content


def _decode_html(content: bytes, response: requests.Response) -> str:
    encoding = response.encoding or getattr(response, "apparent_encoding", None)
    if encoding:
        try:
            return content.decode(encoding, errors="replace")
        except (LookupError, TypeError):
            pass
    return content.decode("utf-8", errors="replace")


def _extract_html(response: requests.Response, *, max_bytes: int) -> str:
    _ensure_textual_response(response)
    content = _materialize_content(response, max_bytes=max_bytes)
    return _decode_html(content, response)


DOCUMENTATION_KEYWORDS: tuple[str, ...] = (
    # B1 – Documentation completeness
    "doc",
    "docs",
    "documentation",
    "manual",
    "user manual",
    "handbook",
    "guide",
    "usage guide",
    "usage",
    "how to",
    "how-to",
    "tutorial",
    "walkthrough",
    "quickstart",
    "getting started",
    "examples",
    "example",
    "sample",
    "cookbook",
    "reference",
    "api reference",
    "start here",
    "first steps",
    "example workflow",
    "usage:",
    "--help",
    "cli",
    "gui",
    "web app",
    "rest api",
    "openapi",
    "swagger",
    "galaxy",
    "shiny",
    "streamlit",
    "gradio",
    # B2 – Installation pathways
    "install",
    "installation",
    "setup",
    "set up",
    "pip install",
    "pip3 install",
    "conda install",
    "mamba install",
    "bioconda",
    "bioconductor",
    "cran",
    "brew install",
    "apt-get install",
    "docker",
    "dockerfile",
    "docker pull",
    "container",
    "singularity",
    "singularity recipe",
    "apptainer",
    "podman",
    "biocontainers",
    "ghcr.io",
    "quay.io",
    "requirements.txt",
    "environment.yml",
    "env.yaml",
    "poetry.lock",
    "pipfile",
    "build",
    "compile",
    "binary",
    "package",
    # B3 – Reproducibility aids
    "release",
    "release date",
    "latest release",
    "releases",
    "changelog",
    "version",
    "version history",
    "tag",
    "git tag",
    "tags",
    "doi",
    "zenodo",
    "license",
    "mit",
    "gpl",
    "apache",
    "bsd",
    "archival",
    "workflow",
    "pipeline",
    "makefile",
    "test data",
    "sample dataset",
    "exact command",
    "reproduce",
    "replicate",
    "benchmark",
    # B4 – Maintenance signal
    "updated",
    "last updated",
    "commit",
    "recent commit",
    "activity",
    "roadmap",
    "issue tracker",
    "issues",
    "open issues",
    "closed issues",
    "news",
    "blog",
    "maintained",
    "supported",
    "support",
    "active",
    # B5 – Onboarding & support
    "help",
    "faq",
    "troubleshooting",
    "contact",
    "email",
    "support@",
    "community",
    "forum",
    "contributing",
    "contribution guide",
    "code of conduct",
)

REPOSITORY_HOSTS: tuple[str, ...] = (
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "codeberg.org",
    "gitee.com",
    "sourceforge.net",
    "git.sr.ht",
    "launchpad.net",
)

_LAYOUT_PARENT_NAMES = {"nav", "header", "footer", "aside"}
_LAYOUT_ATTR_KEYWORDS = (
    "header",
    "footer",
    "nav",
    "menu",
    "breadcrumb",
    "sidebar",
    "toolbar",
    "subnav",
    "pagehead",
    "repository-content-header",
    "gh-header",
    "site-footer",
    "site-header",
)

_REPO_NAV_PATH_PREFIXES = (
    "/issues",
    "/pulls",
    "/pull",
    "/actions",
    "/projects",
    "/security",
    "/discussions",
    "/packages",
    "/marketplace",
    "/sponsors",
    "/network",
    "/graphs",
    "/pulse",
)

_REPO_NAV_TEXT = {
    "issues",
    "pull requests",
    "pull request",
    "actions",
    "security",
    "projects",
    "insights",
    "code",
    "sponsors",
    "packages",
    "discussions",
    "marketplace",
    "network",
    "graphs",
    "pulse",
}


def _iter_attribute_tokens(node: Tag) -> Iterable[str]:
    for attr_name in ("class", "id", "role", "aria-label", "data-testid"):
        attr = node.attrs.get(attr_name)
        if not attr:
            continue
        if isinstance(attr, (list, tuple, set)):
            for item in attr:
                token = str(item).strip().lower()
                if token:
                    yield token
        else:
            token = str(attr).strip().lower()
            if token:
                yield token


def _is_layout_container(node: Tag) -> bool:
    tag_name = (node.name or "").lower() if isinstance(node, Tag) else ""
    if tag_name in _LAYOUT_PARENT_NAMES:
        return True
    for token in _iter_attribute_tokens(node):
        for keyword in _LAYOUT_ATTR_KEYWORDS:
            if keyword in token:
                return True
    return False


def _is_layout_ancestor(anchor: Tag, max_depth: int = 4) -> bool:
    depth = 0
    for parent in anchor.parents:
        if not isinstance(parent, Tag):
            continue
        if _is_layout_container(parent):
            return True
        depth += 1
        if depth >= max_depth:
            break
    return False


def _sanitize_anchor_text(anchor: Tag) -> str:
    return anchor.get_text(separator=" ", strip=True)


def _match_documentation_keywords(text_lower: str, href_lower: str) -> list[str]:
    matches: list[str] = []
    for keyword in DOCUMENTATION_KEYWORDS:
        lowered = keyword.lower()
        if lowered in text_lower or lowered in href_lower:
            matches.append(keyword)
    return matches


def _is_repo_navigation_link(resolved_url: str, anchor_text: str) -> bool:
    try:
        parsed = urlparse(resolved_url)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    if not host or host not in REPOSITORY_HOSTS:
        return False
    path_lower = (parsed.path or "").lower()
    text_lower = anchor_text.strip().lower()
    if text_lower in _REPO_NAV_TEXT:
        return True
    for prefix in _REPO_NAV_PATH_PREFIXES:
        if path_lower == prefix or path_lower.startswith(prefix + "/"):
            return True
    return False


PUBLICATION_HOST_KEYWORDS: tuple[str, ...] = (
    "doi.org",
    "dx.doi.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "link.springer.com",
    "nature.com",
    "sciencedirect.com",
    "academic.oup.com",
    "onlinelibrary.wiley.com",
    "biomedcentral.com",
    "journals.plos.org",
    "frontiersin.org",
    "researchgate.net",
    "biorxiv.org",
    "medrxiv.org",
    "ieeexplore.ieee.org",
    "dl.acm.org",
    "jamanetwork.com",
    "science.org",
    "cell.com",
    "hindawi.com",
    "tandfonline.com",
    "karger.com",
    "spiedigitallibrary.org",
    "iop.org",
)

_DOI_PATH_PATTERN = re.compile(r"/10\.[0-9]{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)

__all__ = [
    "DOCUMENTATION_KEYWORDS",
    "REPOSITORY_HOSTS",
    "extract_homepage",
    "fetch_with_timeout",
    "extract_metadata",
    "scrape_homepage_metadata",
    "is_probable_publication_url",
]


def is_probable_publication_url(url: str | None) -> bool:
    if not isinstance(url, str):
        return False
    candidate = url.strip()
    if not candidate:
        return False
    try:
        parsed = urlparse(candidate)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if not host:
        return False
    if any(keyword in host for keyword in PUBLICATION_HOST_KEYWORDS):
        return True
    if host.endswith(".nih.gov") and ("pmc" in host or "/pmc" in path):
        return True
    if _DOI_PATH_PATTERN.search(path):
        return True
    return False


def _candidate_homepage_urls(candidate: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        if not raw:
            return
        value = raw
        if isinstance(value, dict):
            value = value.get("url")
        if not isinstance(value, str):
            return
        url = value.strip()
        if not url or url in seen:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            return
        seen.add(url)
        urls.append(url)

    _add(candidate.get("homepage"))
    for extra in candidate.get("urls") or []:
        _add(extra)

    return urls


def _coerce_homepage_status(value: Any) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    text = str(value).strip()
    if not text:
        return None
    match = _NUMERIC_STATUS_PATTERN.match(text)
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            pass
    return text


def normalize_candidate_homepage(candidate: dict[str, Any]) -> None:
    """Normalize homepage metadata fields sourced from Pub2Tools."""

    if not isinstance(candidate, dict):
        return

    status: Any = candidate.get("homepage_status")
    error: Any = candidate.get("homepage_error")
    filtered_url: Any = candidate.get("homepage_filtered_url")

    def _from_mapping(mapping: dict[str, Any]) -> None:
        nonlocal status, error, filtered_url
        if status is None:
            for key in (
                "status_code",
                "statusCode",
                "http_status",
                "httpStatus",
                "status",
                "code",
            ):
                value = mapping.get(key)
                if value not in (None, ""):
                    status = value
                    break
        if error is None:
            for key in (
                "error",
                "message",
                "reason",
                "status_text",
                "statusText",
            ):
                value = mapping.get(key)
                if value not in (None, ""):
                    error = value
                    break
        if filtered_url is None:
            for key in ("filtered_url", "filteredUrl", "filtered"):
                value = mapping.get(key)
                if value not in (None, ""):
                    filtered_url = value
                    break

    raw_homepage = candidate.get("homepage")
    if isinstance(raw_homepage, dict):
        url_value = (
            raw_homepage.get("url")
            or raw_homepage.get("link")
            or raw_homepage.get("href")
        )
        if isinstance(url_value, str) and url_value.strip():
            candidate["homepage"] = url_value.strip()
        _from_mapping(raw_homepage)
    elif isinstance(raw_homepage, list):
        for item in raw_homepage:
            if isinstance(item, str) and item.strip():
                candidate["homepage"] = item.strip()
                break
            if isinstance(item, dict):
                url_value = item.get("url") or item.get("link") or item.get("href")
                if isinstance(url_value, str) and url_value.strip():
                    candidate["homepage"] = url_value.strip()
                _from_mapping(item)
                if candidate.get("homepage"):
                    break
    elif isinstance(raw_homepage, str):
        candidate["homepage"] = raw_homepage.strip()

    if status is None:
        for key in (
            "homepageStatus",
            "homepage_status_code",
            "homepageStatusCode",
            "urlStatus",
            "url_status",
            "urlStatusCode",
        ):
            value = candidate.get(key)
            if value not in (None, ""):
                status = value
                break

    if error is None:
        for key in (
            "homepageError",
            "urlError",
            "homepage_error_message",
            "homepageMessage",
            "url_error",
        ):
            value = candidate.get(key)
            if value not in (None, ""):
                error = value
                break

    if filtered_url is None:
        for key in (
            "homepageFilteredUrl",
            "homepage_filteredUrl",
            "urlFiltered",
        ):
            value = candidate.get(key)
            if value not in (None, ""):
                filtered_url = value
                break

    if status is not None:
        coerced_status = _coerce_homepage_status(status)
        if coerced_status is not None:
            candidate["homepage_status"] = coerced_status

    if error is not None:
        candidate["homepage_error"] = _truncate_error(str(error))

    if filtered_url is not None:
        candidate["homepage_filtered_url"] = str(filtered_url).strip()


def extract_homepage(html_content: str) -> str | None:
    """Extract homepage URL from HTML. Returns None on error or not found."""

    try:
        soup = BeautifulSoup(html_content, "html.parser")
        for anchor in soup.find_all("a", href=True):
            if "home" in anchor.get_text().lower():
                return anchor["href"]
    except Exception:
        return None
    return None


def fetch_with_timeout(url: str, timeout: float = 1.0):
    """Stubbed helper used in legacy tests to simulate a timeout."""

    time.sleep(timeout * 2)
    raise TimeoutError(f"Timeout fetching {url}")


def _merge_metadata(into: dict[str, Any], addition: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(into)
    docs = set(into.get("documentation", []) or [])
    docs.update(addition.get("documentation", []) or [])
    if docs:
        merged["documentation"] = sorted(docs)

    keywords = set(into.get("documentation_keywords", []) or [])
    keywords.update(addition.get("documentation_keywords", []) or [])
    if keywords:
        merged["documentation_keywords"] = sorted(keywords)
    elif "documentation_keywords" in merged and not keywords:
        merged.pop("documentation_keywords", None)

    if not merged.get("repository") and addition.get("repository"):
        merged["repository"] = addition["repository"]
    return merged


def extract_metadata(html_content: str, base_url: str) -> dict[str, Any]:
    """Extract documentation and repository links from HTML content."""

    soup = BeautifulSoup(html_content, "html.parser")
    meta: dict[str, Any] = {}
    documentation: list[str] = []
    documentation_seen: set[str] = set()
    repository: str | None = None
    found_keywords: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href:
            continue
        if href.startswith("#"):
            continue

        text_raw = _sanitize_anchor_text(anchor)
        text_lower = text_raw.lower()
        href_lower = href.lower()
        resolved = urljoin(base_url, href)

        try:
            resolved_host = urlparse(resolved).netloc.lower()
        except Exception:
            resolved_host = ""

        if resolved_host in REPOSITORY_HOSTS and not repository:
            repository = resolved

        matching_keywords = _match_documentation_keywords(text_lower, href_lower)

        if _is_repo_navigation_link(resolved, text_raw):
            continue

        if _is_layout_ancestor(anchor) and not matching_keywords:
            continue

        if matching_keywords and resolved not in documentation_seen:
            documentation.append(resolved)
            documentation_seen.add(resolved)
        found_keywords.update(keyword.lower() for keyword in matching_keywords)

    if documentation:
        meta["documentation"] = documentation
    if found_keywords:
        meta["documentation_keywords"] = sorted(found_keywords)
    if repository:
        meta["repository"] = repository
    return meta


def _discover_frame_urls(html_content: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html_content, "html.parser")
    frame_urls: list[str] = []
    for tag_name in ("frame", "iframe"):
        for tag in soup.find_all(tag_name):
            src = tag.get("src")
            if not src:
                continue
            resolved = urljoin(base_url, src)
            frame_urls.append(resolved)
    return frame_urls


def _crawl_frames_for_metadata(
    root_html: str,
    root_url: str,
    *,
    session: requests.Session,
    headers: dict[str, str],
    timeout: float,
    max_frames: int,
    max_depth: int,
    max_bytes: int,
    logger,
) -> dict[str, Any]:
    if max_frames <= 0 or max_depth <= 0:
        return {}

    aggregated: dict[str, Any] = {}
    visited: set[str] = set()
    queue: deque[tuple[str, str, int]] = deque([(root_html, root_url, 0)])
    fetched = 0

    while queue and fetched < max_frames:
        html, base_url, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for frame_url in _discover_frame_urls(html, base_url):
            if frame_url in visited:
                continue
            visited.add(frame_url)
            if fetched >= max_frames:
                break
            try:
                response = session.get(frame_url, timeout=timeout, headers=headers)
                fetched += 1
                if response.status_code >= 400:
                    logger.warning(
                        "SCRAPE frame %s failed with HTTP %s",
                        frame_url,
                        response.status_code,
                    )
                    continue
                frame_html = _extract_html(response, max_bytes=max_bytes)
            except ContentTooLargeError as exc:
                logger.warning("SCRAPE frame %s skipped: %s", frame_url, exc)
                continue
            except NonHtmlContentError as exc:
                logger.warning("SCRAPE frame %s skipped: %s", frame_url, exc)
                continue
            except Exception as exc:  # pragma: no cover - network specific failures
                logger.warning("SCRAPE frame fetch failed for %s: %s", frame_url, exc)
                continue

            frame_meta = extract_metadata(frame_html, frame_url)
            if frame_meta:
                aggregated = (
                    _merge_metadata(aggregated, frame_meta)
                    if aggregated
                    else dict(frame_meta)
                )

            if depth + 1 < max_depth:
                queue.append((frame_html, frame_url, depth + 1))

    return aggregated


def _normalize_doc_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                url = item.get("url")
                if url:
                    urls.append(str(url))
            elif isinstance(item, str):
                urls.append(item)
    elif isinstance(value, dict):
        url = value.get("url")
        if url:
            urls.append(str(url))
    elif isinstance(value, str):
        urls.append(value)
    return urls


def _merge_documentation(candidate: dict[str, Any], new_urls: Iterable[str]) -> None:
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in candidate.get("documentation") or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if url and url not in seen:
                seen.add(url)
                docs.append(
                    {"url": url, **{k: v for k, v in item.items() if k != "url"}}
                )
        elif isinstance(item, str):
            url = item.strip()
            if url and url not in seen:
                seen.add(url)
                docs.append({"url": url})

    for raw in new_urls:
        url = str(raw).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        docs.append({"url": url, "type": ["Documentation"]})

    if docs:
        candidate["documentation"] = docs


def scrape_homepage_metadata(
    candidate: dict[str, Any],
    *,
    config: dict[str, Any] | None,
    logger,
    session: requests.Session | None = None,
) -> None:
    """Fetch homepage HTML and enrich candidate with documentation/repository links."""
    normalize_candidate_homepage(candidate)
    cfg = config or {}
    homepage_candidates = _candidate_homepage_urls(candidate)
    if not homepage_candidates:
        return

    homepage = homepage_candidates[0]
    if is_probable_publication_url(homepage):
        alternative = next(
            (
                url
                for url in homepage_candidates
                if not is_probable_publication_url(url)
            ),
            None,
        )
        if alternative:
            homepage = alternative
        else:
            candidate.pop("homepage", None)
            candidate.pop("homepage_status", None)
            candidate.pop("homepage_filtered_url", None)
            candidate["homepage_error"] = "filtered_publication_url"
            candidate["homepage_scraped"] = False
            return

    if candidate.get("homepage") != homepage:
        candidate["homepage"] = homepage

    timeout = cfg.get("timeout", 8)
    headers = {"User-Agent": cfg.get("user_agent", DEFAULT_USER_AGENT)}
    max_bytes = int(cfg.get("max_bytes", DEFAULT_MAX_BYTES))
    if max_bytes <= 0:
        max_bytes = DEFAULT_MAX_BYTES
    max_frames = int(cfg.get("max_frames", DEFAULT_MAX_FRAME_FETCHES))
    if max_frames < 0:
        max_frames = 0
    max_frame_depth = int(cfg.get("max_frame_depth", DEFAULT_MAX_FRAME_DEPTH))
    if max_frame_depth < 0:
        max_frame_depth = 0

    sess = session or requests.Session()

    try:
        response = sess.get(homepage, timeout=timeout, headers=headers)
    except (
        Exception
    ) as exc:  # pragma: no cover - network failures are environment-specific
        status_label, message = _classify_homepage_exception(exc)
        candidate["homepage_status"] = status_label
        candidate["homepage_error"] = message or status_label
        candidate["homepage_scraped"] = False
        logger.warning("SCRAPE failed for %s: %s", homepage, exc)
        return

    candidate["homepage_status"] = response.status_code
    if response.status_code >= 400:
        candidate["homepage_error"] = f"HTTP {response.status_code}"
        candidate["homepage_scraped"] = False
        return

    try:
        html = _extract_html(response, max_bytes=max_bytes)
    except ContentTooLargeError as exc:
        candidate["homepage_status"] = "content_too_large"
        candidate["homepage_error"] = _truncate_error(str(exc))
        candidate["homepage_scraped"] = False
        logger.warning("SCRAPE skipped %s: %s", homepage, exc)
        return
    except NonHtmlContentError as exc:
        candidate["homepage_status"] = "non_html_content"
        candidate["homepage_error"] = _truncate_error(str(exc))
        candidate["homepage_scraped"] = False
        logger.warning("SCRAPE skipped %s: %s", homepage, exc)
        return

    candidate.pop("homepage_error", None)

    meta = extract_metadata(html, homepage)

    frame_meta = _crawl_frames_for_metadata(
        html,
        homepage,
        session=sess,
        headers=headers,
        timeout=timeout,
        max_frames=max_frames,
        max_depth=max_frame_depth,
        max_bytes=max_bytes,
        logger=logger,
    )
    if frame_meta:
        meta = _merge_metadata(meta, frame_meta) if meta else frame_meta

    docs = meta.get("documentation", []) if meta else []
    if docs:
        _merge_documentation(candidate, docs)
    repo = meta.get("repository") if meta else None
    if repo and not candidate.get("repository"):
        candidate["repository"] = repo
    keywords = meta.get("documentation_keywords") if meta else None
    if keywords:
        candidate["documentation_keywords"] = keywords
    else:
        candidate.pop("documentation_keywords", None)
    candidate["homepage_scraped"] = True
