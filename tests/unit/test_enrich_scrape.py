from __future__ import annotations

from pathlib import Path
from typing import Any


def test_extract_metadata_from_html(tmp_path: Path) -> None:
    """Extract documentation and repo links from simple HTML."""
    from biotoolsllmannotate.enrich import scraper

    html = (
        "<html><head><title>Tool</title></head>"
        "<body>"
        '<a href="/docs">Documentation</a>'
        '<a href="https://github.com/org/tool">Source</a>'
        "</body></html>"
    )
    base = "https://example.org/tool"
    meta = scraper.extract_metadata(html, base)
    assert any("/docs" in u for u in meta.get("documentation", []))
    assert meta.get("repository") == "https://github.com/org/tool"


def test_extract_metadata_supports_additional_repo_hosts() -> None:
    """Recognize repository hosts beyond the default set."""
    from biotoolsllmannotate.enrich import scraper

    new_hosts = [
        "codeberg.org",
        "gitee.com",
        "sourceforge.net",
        "git.sr.ht",
        "launchpad.net",
    ]
    for host in new_hosts:
        url = f"https://{host}/org/tool"
        html = f'<html><body><a href="{url}">Repository</a></body></html>'
        meta = scraper.extract_metadata(html, url)
        assert meta.get("repository") == url


def test_extract_metadata_with_tutorial_link() -> None:
    """Capture tutorial anchor tags as documentation."""
    from biotoolsllmannotate.enrich import scraper

    html = "<html><body>" '<a href="/learn">Tutorial</a>' "</body></html>"
    base = "https://example.org/tool"
    assert "tutorial" in scraper.DOCUMENTATION_KEYWORDS
    meta = scraper.extract_metadata(html, base)
    assert any("/learn" in u for u in meta.get("documentation", []))
    assert meta.get("documentation_keywords") == ["tutorial"]


def test_extract_metadata_with_install_keyword() -> None:
    """Find installation keywords in documentation anchors."""
    from biotoolsllmannotate.enrich import scraper

    html = (
        "<html><body>" '<a href="/install">Install via pip install</a>' "</body></html>"
    )
    base = "https://example.org/tool"
    assert "install" in scraper.DOCUMENTATION_KEYWORDS
    assert "pip install" in scraper.DOCUMENTATION_KEYWORDS
    meta = scraper.extract_metadata(html, base)
    assert any("/install" in u for u in meta.get("documentation", []))
    assert meta.get("documentation_keywords") == ["install", "pip install"]


def test_scrape_homepage_clears_stale_error() -> None:
    """Successful scrape removes a stale homepage error flag."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        encoding = "utf-8"
        _text = '<html><body><a href="/docs">Documentation</a></body></html>'
        content = _text.encode("utf-8")

        @property
        def text(self) -> str:
            return self._text

    class DummySession:
        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:  # pragma: no cover - simple stub
            self.last_request = (url, timeout, headers)
            return DummyResponse()

    class DummyLogger:
        def warning(
            self, *args: Any, **kwargs: Any
        ) -> None:  # pragma: no cover - nothing to log on success
            return None

    candidate = {
        "homepage": "https://example.org/tool",
        "homepage_error": "previous failure",
    }
    config = {"timeout": 5, "user_agent": "unit-test-agent"}

    scrape_homepage_metadata(
        candidate, config=config, logger=DummyLogger(), session=DummySession()
    )

    assert candidate.get("homepage_status") == 200
    assert "homepage_error" not in candidate
    assert candidate.get("homepage_scraped") is True
    assert candidate.get("documentation_keywords") == ["doc", "documentation"]


def test_scrape_homepage_removes_absent_keywords() -> None:
    """Scrape clears documentation keywords when none are found."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        encoding = "utf-8"
        _text = "<html><body><p>No docs here</p></body></html>"
        content = _text.encode("utf-8")

        @property
        def text(self) -> str:
            return self._text

    class DummySession:
        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:
            return DummyResponse()

    class DummyLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            return None

    candidate = {
        "homepage": "https://example.org/tool",
        "documentation_keywords": ["tutorial"],
    }

    scrape_homepage_metadata(
        candidate, config={}, logger=DummyLogger(), session=DummySession()
    )

    assert candidate.get("documentation_keywords") is None


def test_scrape_homepage_follows_frames() -> None:
    """Scrape traverses frames to aggregate documentation metadata."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        def __init__(self, text: str) -> None:
            self.status_code = 200
            self.headers = {"Content-Type": "text/html"}
            self.encoding = "utf-8"
            self._text = text
            self.content = text.encode("utf-8")

        @property
        def text(self) -> str:
            return self._text

    class DummySession:
        def __init__(self) -> None:
            self.calls = []

        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:
            self.calls.append(url)
            if url == "https://example.org/tool":
                return DummyResponse(
                    """
                    <html>
                      <frameset>
                        <frame src="/embedded/docs" />
                      </frameset>
                    </html>
                    """
                )
            elif url == "https://example.org/embedded/docs":
                return DummyResponse(
                    """
                    <html><body>
                      <a href="/manual">Installation and Usage guide</a>
                    </body></html>
                    """
                )
            raise AssertionError(f"Unexpected URL requested: {url}")

    class DummyLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError(f"Unexpected warning: {args}")

    candidate = {
        "homepage": "https://example.org/tool",
    }

    scrape_homepage_metadata(
        candidate,
        config={"max_frames": 2},
        logger=DummyLogger(),
        session=DummySession(),
    )

    assert candidate.get("homepage_scraped") is True
    keywords = candidate.get("documentation_keywords") or []
    assert "installation" in keywords
    assert "usage" in keywords or "usage guide" in keywords
    docs = {d.get("url") for d in candidate.get("documentation", [])}
    assert "https://example.org/manual" in docs


def test_scrape_homepage_skips_publication_link() -> None:
    """Publication URLs are filtered prior to scraping."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummySession:
        def get(self, url: str, timeout: float | int, headers: dict[str, str]) -> None:
            raise AssertionError("Should not fetch publication URLs")

    class DummyLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("No warnings expected")

    candidate = {
        "homepage": "https://doi.org/10.1000/example",
    }

    scrape_homepage_metadata(
        candidate,
        config={},
        logger=DummyLogger(),
        session=DummySession(),
    )

    assert candidate.get("homepage") is None
    assert "homepage_filtered_url" not in candidate
    assert candidate.get("homepage_error") == "filtered_publication_url"


def test_scrape_homepage_records_connection_error() -> None:
    """Network failures produce connection_error status metadata."""
    import requests

    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummySession:
        def get(self, url: str, timeout: float | int, headers: dict[str, str]) -> None:
            raise requests.exceptions.ConnectionError("DNS failure")

    class DummyLogger:
        def __init__(self) -> None:
            self.messages = []

        def warning(self, *args: Any, **kwargs: Any) -> None:
            self.messages.append(args)

    candidate = {
        "homepage": "https://missing.example",
    }

    scrape_homepage_metadata(
        candidate, config={}, logger=DummyLogger(), session=DummySession()
    )

    assert candidate.get("homepage_status") == "connection_error"
    homepage_error = candidate.get("homepage_error") or ""
    assert "DNS failure" in homepage_error
    assert candidate.get("homepage_scraped") is False
    assert candidate.get("homepage_scraped") is False
    assert "documentation" not in candidate
    assert candidate.get("documentation_keywords") is None


def test_scrape_homepage_prefers_non_publication_url() -> None:
    """Scraper prefers non-publication URLs when available."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        status_code = 200
        headers = {"Content-Type": "text/html"}
        encoding = "utf-8"
        _text = '<html><body><a href="/docs">Documentation</a></body></html>'
        content = _text.encode("utf-8")

        @property
        def text(self) -> str:
            return self._text

    class DummySession:
        def __init__(self) -> None:
            self.calls = []

        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:
            self.calls.append(url)
            if url == "https://example.org/tool":
                return DummyResponse()
            raise AssertionError(f"Unexpected URL fetched: {url}")

    class DummyLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("No warnings expected")

    candidate = {
        "homepage": "https://doi.org/10.1000/example",
        "urls": ["https://example.org/tool"],
    }

    session = DummySession()
    scrape_homepage_metadata(
        candidate,
        config={},
        logger=DummyLogger(),
        session=session,
    )

    assert candidate.get("homepage") == "https://example.org/tool"
    assert session.calls == ["https://example.org/tool"]
    assert candidate.get("homepage_scraped") is True
    docs = candidate.get("documentation") or []
    doc_urls = {entry.get("url") for entry in docs}
    assert "https://example.org/docs" in doc_urls


def test_scrape_homepage_rejects_non_html() -> None:
    """Non-HTML responses are rejected with non_html_content status."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        status_code = 200
        headers = {"Content-Type": "application/pdf"}
        encoding = "utf-8"
        _text = "%PDF"
        content = b"%PDF-1.5"

        @property
        def text(self) -> str:
            return self._text

    class DummySession:
        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:
            return DummyResponse()

    class DummyLogger:
        def __init__(self) -> None:
            self.messages = []

        def warning(self, *args: Any, **kwargs: Any) -> None:
            self.messages.append(args)

    candidate = {"homepage": "https://example.org/tool"}

    scrape_homepage_metadata(
        candidate,
        config={},
        logger=DummyLogger(),
        session=DummySession(),
    )

    assert candidate.get("homepage_status") == "non_html_content"
    assert candidate.get("homepage_scraped") is False
    assert "homepage_error" in candidate


def test_scrape_homepage_enforces_byte_guardrail() -> None:
    """Content length exceeding guardrail marks scrape as too large."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        def __init__(self, size: int) -> None:
            self.status_code = 200
            self.headers = {
                "Content-Type": "text/html",
                "Content-Length": str(size),
            }
            self.encoding = "utf-8"
            self._text = "<html><body>" + ("x" * size) + "</body></html>"
            self.content = self._text.encode("utf-8")

        @property
        def text(self) -> str:  # pragma: no cover - legacy compatibility
            return self._text

    class DummySession:
        def __init__(self, size: int) -> None:
            self.size = size

        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:
            return DummyResponse(self.size)

    class DummyLogger:
        def __init__(self) -> None:
            self.messages = []

        def warning(self, *args: Any, **kwargs: Any) -> None:
            self.messages.append(args)

    candidate = {"homepage": "https://example.org/tool"}

    scrape_homepage_metadata(
        candidate,
        config={"max_bytes": 64},
        logger=DummyLogger(),
        session=DummySession(size=1_000),
    )

    assert candidate.get("homepage_status") == "content_too_large"
    assert candidate.get("homepage_scraped") is False
    assert "homepage_error" in candidate
