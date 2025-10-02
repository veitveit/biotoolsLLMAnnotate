def test_extract_metadata_from_html(tmp_path):
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


def test_extract_metadata_supports_additional_repo_hosts():
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


def test_extract_metadata_with_tutorial_link():
    from biotoolsllmannotate.enrich import scraper

    html = "<html><body>" '<a href="/learn">Tutorial</a>' "</body></html>"
    base = "https://example.org/tool"
    assert "tutorial" in scraper.DOCUMENTATION_KEYWORDS
    meta = scraper.extract_metadata(html, base)
    assert any("/learn" in u for u in meta.get("documentation", []))
    assert meta.get("documentation_keywords") == ["tutorial"]


def test_extract_metadata_with_install_keyword():
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


def test_scrape_homepage_clears_stale_error():
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        status_code = 200
        text = '<html><body><a href="/docs">Documentation</a></body></html>'

    class DummySession:
        def get(self, url, timeout, headers):  # pragma: no cover - simple stub
            self.last_request = (url, timeout, headers)
            return DummyResponse()

    class DummyLogger:
        def warning(
            self, *args, **kwargs
        ):  # pragma: no cover - nothing to log on success
            pass

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


def test_scrape_homepage_removes_absent_keywords():
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        status_code = 200
        text = "<html><body><p>No docs here</p></body></html>"

    class DummySession:
        def get(self, url, timeout, headers):
            return DummyResponse()

    class DummyLogger:
        def warning(self, *args, **kwargs):
            pass

    candidate = {
        "homepage": "https://example.org/tool",
        "documentation_keywords": ["tutorial"],
    }

    scrape_homepage_metadata(
        candidate, config={}, logger=DummyLogger(), session=DummySession()
    )

    assert candidate.get("documentation_keywords") is None


def test_scrape_homepage_follows_frames():
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        def __init__(self, text):
            self.status_code = 200
            self.text = text

    class DummySession:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout, headers):
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
        def warning(self, *args, **kwargs):
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


def test_scrape_homepage_skips_publication_link():
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummySession:
        def get(self, url, timeout, headers):
            raise AssertionError("Should not fetch publication URLs")

    class DummyLogger:
        def warning(self, *args, **kwargs):
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
    assert candidate.get("homepage_scraped") is False
    assert "documentation" not in candidate
    assert candidate.get("documentation_keywords") is None


def test_scrape_homepage_prefers_non_publication_url():
    from biotoolsllmannotate.enrich.scraper import scrape_homepage_metadata

    class DummyResponse:
        status_code = 200
        text = '<html><body><a href="/docs">Documentation</a></body></html>'

    class DummySession:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout, headers):
            self.calls.append(url)
            if url == "https://example.org/tool":
                return DummyResponse()
            raise AssertionError(f"Unexpected URL fetched: {url}")

    class DummyLogger:
        def warning(self, *args, **kwargs):
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
