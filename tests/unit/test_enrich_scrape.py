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
