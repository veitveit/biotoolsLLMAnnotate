from __future__ import annotations

import pytest

from biotoolsllmannotate.enrich.scraper import fetch_with_timeout


def test_timeout() -> None:
    """Fetch helper raises TimeoutError when exceeding limit."""
    with pytest.raises(TimeoutError):
        fetch_with_timeout("http://example.com", timeout=0.0001)
