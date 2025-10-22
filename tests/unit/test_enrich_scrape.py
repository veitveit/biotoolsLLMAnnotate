from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TESTS_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"
HTML_DIR = FIXTURES_DIR / "html"


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


def test_extract_metadata_ignores_repository_navigation_noise() -> None:
    """Repository nav links should not inflate documentation evidence."""
    from biotoolsllmannotate.enrich import scraper

    html = """
        <html>
            <body>
                <header class="pagehead">
                    <nav class="UnderlineNav">
                        <a class="UnderlineNav-item" href="/org/tool">Code</a>
                        <a class="UnderlineNav-item" href="/org/tool/issues">Issues</a>
                        <a class="UnderlineNav-item" href="/org/tool/pulls">Pull requests</a>
                        <a class="UnderlineNav-item" href="/org/tool/wiki">Wiki</a>
                    </nav>
                </header>
                <div class="repository-content">
                    <article>
                        <a href="/org/tool/wiki/Getting-Started">Getting started guide</a>
                        <a href="/org/tool/blob/main/README.md">Documentation</a>
                    </article>
                </div>
            </body>
        </html>
        """
    base = "https://github.com/org/tool"
    meta = scraper.extract_metadata(html, base)

    docs = meta.get("documentation") or []
    assert all("issues" not in url for url in docs)
    assert all("pull" not in url for url in docs)
    assert any("Getting-Started" in url for url in docs)
    assert meta.get("repository") == "https://github.com/org/tool"

    keywords = set(meta.get("documentation_keywords") or [])
    assert "issues" not in keywords
    assert any(key in keywords for key in ("getting started", "documentation"))


def test_extract_metadata_keeps_docs_inside_nav_when_relevant() -> None:
    """Navigation containers with real doc links should still be captured."""
    from biotoolsllmannotate.enrich import scraper

    html = """
        <html>
            <body>
                <nav class="site-nav">
                    <a href="/documentation">Documentation</a>
                </nav>
                <main>
                    <a href="/guides/getting-started">Getting Started Guide</a>
                </main>
            </body>
        </html>
        """
    base = "https://docs.example.org/tool/"
    meta = scraper.extract_metadata(html, base)

    docs = meta.get("documentation") or []
    assert any(url.endswith("/documentation") for url in docs)
    assert any("getting-started" in url for url in docs)
    keywords = set(meta.get("documentation_keywords") or [])
    assert "documentation" in keywords
    assert "getting started" in keywords


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


def test_extract_metadata_with_interface_keywords() -> None:
    """Capture interface and usage keywords from anchor text."""
    from biotoolsllmannotate.enrich import scraper

    html = '<html><body><a href="/usage">Usage: CLI (--help)</a></body></html>'
    base = "https://example.org/tool"
    for keyword in ("usage:", "--help", "cli"):
        assert keyword in scraper.DOCUMENTATION_KEYWORDS
    meta = scraper.extract_metadata(html, base)
    keywords = meta.get("documentation_keywords") or []
    assert {"--help", "cli", "usage", "usage:"}.issubset(set(keywords))


def test_extract_metadata_with_release_license_keywords() -> None:
    """Detect release and license keywords in links."""
    from biotoolsllmannotate.enrich import scraper

    html = (
        "<html><body>"
        '<a href="/releases">Releases & License (MIT) tags</a>'
        "</body></html>"
    )
    base = "https://example.org/tool"
    for keyword in ("releases", "license", "mit"):
        assert keyword in scraper.DOCUMENTATION_KEYWORDS
    meta = scraper.extract_metadata(html, base)
    keywords = meta.get("documentation_keywords") or []
    assert {"license", "mit", "releases", "tags"}.issubset(set(keywords))


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
    metrics = candidate.get("homepage_metrics") or {}
    assert metrics.get("root_status") == 200
    assert metrics.get("frame_fetches", 0) >= 0
    assert "homepage_error_details" not in candidate
    keywords = candidate.get("documentation_keywords") or []
    assert {"doc", "documentation"}.issubset(set(keywords))


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
    metrics = candidate.get("homepage_metrics") or {}
    assert metrics.get("root_status") is None
    details = candidate.get("homepage_error_details") or []
    assert details
    first_error = details[0]
    assert first_error.get("label") == "filtered_publication_url"
    assert first_error.get("url") == "https://doi.org/10.1000/example"
    assert metrics.get("errors") == details


def test_scrape_homepage_metadata_baseline(tmp_path: Path) -> None:
    """Full scrape uses fixtures to confirm metadata footprint."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    root_html = (HTML_DIR / "scraper_baseline_root.html").read_text()
    frame_html = (HTML_DIR / "scraper_baseline_frame.html").read_text()
    expected = json.loads(
        (EXPECTED_DIR / "scraper_baseline_candidate.json").read_text()
    )

    class DummyResponse:
        def __init__(self, text: str) -> None:
            self.status_code = 200
            self.headers = {"Content-Type": "text/html"}
            self.encoding = "utf-8"
            self.content = text.encode("utf-8")

    class FixtureSession:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:
            self.calls.append(url)
            if url == "https://fixture.example/tool":
                return DummyResponse(root_html)
            if url == "https://fixture.example/embedded/install.html":
                return DummyResponse(frame_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

    class SilentLogger:
        def warning(
            self, *args: Any, **kwargs: Any
        ) -> None:  # pragma: no cover - no warnings expected
            raise AssertionError(f"Unexpected warning: {args}")

    candidate = {
        "title": "FixtureTool",
        "homepage": "https://fixture.example/tool",
        "documentation": ["https://fixture.example/old-doc"],
    }

    scrape_homepage_metadata(
        candidate,
        config={"max_frames": 3},
        logger=SilentLogger(),
        session=FixtureSession(),
    )

    assert candidate == expected


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
    metrics = candidate.get("homepage_metrics") or {}
    assert metrics.get("root_status") == "connection_error"
    details = candidate.get("homepage_error_details") or []
    assert details
    first_error = details[0]
    assert first_error.get("label") == "root_fetch"
    assert "DNS failure" in (first_error.get("message") or "")
    assert first_error.get("url") == "https://missing.example"
    assert metrics.get("errors") == details


def test_scrape_homepage_records_frame_limit() -> None:
    """Frame crawl respects max_frames and records telemetry flags."""
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    root_html = """
    <html>
        <body>
            <iframe src="/frame-one.html"></iframe>
            <iframe src="/frame-two.html"></iframe>
        </body>
    </html>
    """.strip()

    frame_html = """
    <html>
        <body>
            <a href="/docs">Docs</a>
        </body>
    </html>
    """.strip()

    class DummyResponse:
        def __init__(self, text: str) -> None:
            self.status_code = 200
            self.headers = {"Content-Type": "text/html"}
            self.encoding = "utf-8"
            self.content = text.encode("utf-8")

    class FixtureSession:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def get(
            self, url: str, timeout: float | int, headers: dict[str, str]
        ) -> DummyResponse:
            self.calls.append(url)
            if url == "https://fixture.example/tool":
                return DummyResponse(root_html)
            if url in (
                "https://fixture.example/frame-one.html",
                "https://fixture.example/frame-two.html",
            ):
                return DummyResponse(frame_html)
            raise AssertionError(f"Unexpected URL requested: {url}")

    class SilentLogger:
        def warning(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError(f"Unexpected warning: {args}")

    candidate = {
        "homepage": "https://fixture.example/tool",
    }

    scrape_homepage_metadata(
        candidate,
        config={"max_frames": 1},
        logger=SilentLogger(),
        session=FixtureSession(),
    )

    metrics = candidate.get("homepage_metrics") or {}
    assert metrics.get("frame_fetches") == 1
    assert metrics.get("frame_limit_reached") is True
    assert metrics.get("frame_successes") == 1
    assert not metrics.get("errors")
    assert candidate.get("homepage_error_details") is None


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
