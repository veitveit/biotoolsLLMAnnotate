from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

DEFAULT_USER_AGENT = (
    "biotoolsllmannotate/0.9.1 (+https://github.com/ELIXIR-Belgium/biotoolsLLMAnnotate)"
)

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
    # B2 – Installation pathways
    "install",
    "installation",
    "setup",
    "set up",
    "pip install",
    "pip3 install",
    "conda install",
    "mamba install",
    "docker",
    "dockerfile",
    "container",
    "singularity",
    "singularity recipe",
    "podman",
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
    "changelog",
    "version history",
    "tag",
    "git tag",
    "doi",
    "zenodo",
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

__all__ = [
    "DOCUMENTATION_KEYWORDS",
    "REPOSITORY_HOSTS",
    "extract_homepage",
    "fetch_with_timeout",
    "extract_metadata",
    "scrape_homepage_metadata",
]


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


def extract_metadata(html_content: str, base_url: str) -> dict[str, Any]:
    """Extract documentation and repository links from HTML content."""

    soup = BeautifulSoup(html_content, "html.parser")
    meta: dict[str, Any] = {}
    documentation: list[str] = []
    repository: str | None = None
    found_keywords: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = anchor.get_text().lower()
        resolved = urljoin(base_url, href)
        matching_keywords = [
            keyword for keyword in DOCUMENTATION_KEYWORDS if keyword in text
        ]
        if matching_keywords:
            documentation.append(resolved)
            found_keywords.update(matching_keywords)
        if any(host in href for host in REPOSITORY_HOSTS):
            repository = resolved

    if documentation:
        meta["documentation"] = documentation
    if found_keywords:
        meta["documentation_keywords"] = sorted(found_keywords)
    if repository:
        meta["repository"] = repository
    return meta


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

    cfg = config or {}
    homepage = candidate.get("homepage")
    if not isinstance(homepage, str) or not homepage.strip():
        for url in candidate.get("urls") or []:
            candidate_url = str(url).strip()
            if candidate_url.startswith("http://") or candidate_url.startswith(
                "https://"
            ):
                homepage = candidate_url
                break
    if not homepage:
        return

    timeout = cfg.get("timeout", 8)
    headers = {"User-Agent": cfg.get("user_agent", DEFAULT_USER_AGENT)}
    sess = session or requests.Session()

    try:
        response = sess.get(homepage, timeout=timeout, headers=headers)
        candidate["homepage_status"] = response.status_code
        if response.status_code >= 400:
            candidate["homepage_error"] = f"HTTP {response.status_code}"
            return
        html = response.text
        candidate.pop("homepage_error", None)
    except (
        Exception
    ) as exc:  # pragma: no cover - network failures are environment-specific
        candidate["homepage_status"] = None
        candidate["homepage_error"] = str(exc)
        logger.warning("SCRAPE failed for %s: %s", homepage, exc)
        return

    meta = extract_metadata(html, homepage)
    docs = meta.get("documentation", [])
    if docs:
        _merge_documentation(candidate, docs)
    repo = meta.get("repository")
    if repo and not candidate.get("repository"):
        candidate["repository"] = repo
    keywords = meta.get("documentation_keywords")
    if keywords:
        candidate["documentation_keywords"] = keywords
    else:
        candidate.pop("documentation_keywords", None)
    candidate["homepage_scraped"] = True
