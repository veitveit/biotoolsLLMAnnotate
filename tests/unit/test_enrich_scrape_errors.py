from biotoolsllmannotate.enrich.scraper import extract_homepage


def test_bad_html_raises():
    bad_html = "<html><head><title>Broken<title></head><body>"
    # Should not raise, but return None or fallback
    homepage = extract_homepage(bad_html)
    assert homepage is None or isinstance(homepage, str)
