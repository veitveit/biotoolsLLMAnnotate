from __future__ import annotations

from biotoolsllmannotate.enrich.utils import (
    FrameCrawlLimiter,
    is_probable_publication_url,
    match_documentation_keywords,
)


def test_match_documentation_keywords_matches_text_and_href() -> None:
    matches = match_documentation_keywords("Quickstart Guide", "#")
    assert "quickstart" in {m.lower() for m in matches}

    href_matches = match_documentation_keywords("", "https://example.org/install.txt")
    assert "install" in {m.lower() for m in href_matches}


def test_frame_crawl_limiter_enforces_limits() -> None:
    limiter = FrameCrawlLimiter(max_frames=2, max_depth=1)

    assert limiter.can_fetch_more() is True
    assert limiter.depth_allowed(0) is True
    assert limiter.depth_allowed(1) is False  # depth limit reached
    assert limiter.depth_limit_hit is True

    limiter.record_fetch()
    assert limiter.fetches == 1
    assert limiter.can_fetch_more() is True

    limiter.record_fetch()
    assert limiter.fetches == 2
    assert limiter.limit_reached is True
    assert limiter.can_fetch_more() is False


def test_is_probable_publication_url_detects_doi_and_filters_others() -> None:
    assert is_probable_publication_url("https://doi.org/10.1000/example") is True
    assert is_probable_publication_url("https://example.org/tool") is False
    assert is_probable_publication_url("   ") is False
