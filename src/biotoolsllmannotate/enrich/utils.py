from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence
from urllib.parse import urlparse

__all__ = [
    "DOCUMENTATION_KEYWORDS",
    "match_documentation_keywords",
    "FrameCrawlLimiter",
    "is_probable_publication_url",
]


DOCUMENTATION_KEYWORDS: tuple[str, ...] = (
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


def match_documentation_keywords(
    text: str,
    href: str,
    *,
    keywords: Sequence[str] | None = None,
) -> list[str]:
    """Return keywords that appear in either anchor text or its href."""

    matches: list[str] = []
    text_lower = text.lower()
    href_lower = href.lower()
    for keyword in keywords or DOCUMENTATION_KEYWORDS:
        lowered = keyword.lower()
        if lowered in text_lower or lowered in href_lower:
            matches.append(keyword)
    return matches


@dataclass
class FrameCrawlLimiter:
    """Helper to enforce frame crawl limits consistently."""

    max_frames: int
    max_depth: int
    fetches: int = 0
    limit_reached: bool = False
    depth_limit_hit: bool = False

    def __post_init__(self) -> None:
        self.max_frames = max(0, int(self.max_frames))
        self.max_depth = max(0, int(self.max_depth))

    def can_fetch_more(self) -> bool:
        """Return True if another frame fetch is permitted."""

        if self.max_frames == 0:
            self.limit_reached = True
            return False
        if self.fetches >= self.max_frames:
            self.limit_reached = True
            return False
        return True

    def depth_allowed(self, depth: int) -> bool:
        """Return True if crawling at *depth* is permitted."""

        if self.max_depth == 0:
            self.depth_limit_hit = True
            return False
        if depth >= self.max_depth:
            self.depth_limit_hit = True
            return False
        return True

    def record_fetch(self) -> None:
        """Increment fetch count after a successful HTTP request."""

        self.fetches += 1
        if self.max_frames and self.fetches >= self.max_frames:
            self.limit_reached = True


_PUBLICATION_HOST_KEYWORDS: tuple[str, ...] = (
    "doi.org",
    "dx.doi.org",
    "handle.net",
    "orcid.org",
    "pubmed",
    "ncbi.nlm.nih.gov",
    "europepmc.org",
    "nature.com",
    "science.org",
)

_DOI_PATH_PATTERN = re.compile(r"/10\.\d{4,9}/")


def is_probable_publication_url(url: str | None) -> bool:
    """Return True if the URL looks like it points to a publication record."""

    if not url:
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
    if any(keyword in host for keyword in _PUBLICATION_HOST_KEYWORDS):
        return True
    if host.endswith(".nih.gov") and ("pmc" in host or "/pmc" in path):
        return True
    if _DOI_PATH_PATTERN.search(path):
        return True
    return False
