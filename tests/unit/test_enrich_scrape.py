

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
