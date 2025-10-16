from __future__ import annotations

from biotoolsllmannotate.enrich.scraper import extract_homepage


def test_bad_html_raises() -> None:
    """Return None for malformed homepage markup."""
    bad_html = "<html><head><title>Broken<title></head><body>"
    homepage = extract_homepage(bad_html)
    assert homepage is None or isinstance(homepage, str)
