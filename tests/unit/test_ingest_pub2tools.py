from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path


def test_filter_and_dedup_candidates(tmp_path: Path) -> None:
    """Filter stale entries and deduplicate candidates by homepage."""
    from biotoolsllmannotate.ingest import pub2tools_fetcher as pf

    now = datetime.now(UTC)
    recent = (now - timedelta(days=3)).isoformat()
    old = (now - timedelta(days=40)).isoformat()

    data = [
        {
            "id": "a",
            "title": "GeneAnnotator",
            "urls": ["https://ex.org/a"],
            "published_at": recent,
        },
        {
            "id": "b",
            "title": "GeneAnnotator",
            "urls": ["https://ex.org/a"],
            "published_at": recent,
        },
        {
            "id": "c",
            "title": "NotBioApp",
            "urls": ["https://ex.org/c"],
            "published_at": old,
        },
    ]

    since = now - timedelta(days=7)
    out = pf.filter_and_normalize(data, since)
    # Expect dedup by title/homepage and old item filtered out
    titles = [c["title"] for c in out]
    assert titles == ["GeneAnnotator"]


def test_load_from_env_file_normalizes_homepage_metadata(tmp_path: Path) -> None:
    from biotoolsllmannotate.ingest import pub2tools_fetcher as pf

    data = [
        {
            "id": "broken",
            "title": "Broken Tool",
            "homepage": {"url": "https://broken.example", "status": "404"},
            "homepageError": "Not Found",
            "tags": [],
        }
    ]
    fixture = tmp_path / "broken.json"
    fixture.write_text(json.dumps(data), encoding="utf-8")

    loaded = pf.load_from_env_file(fixture)
    assert len(loaded) == 1
    candidate = loaded[0]
    assert candidate["homepage"] == "https://broken.example"
    assert candidate["homepage_status"] == 404
    assert candidate["homepage_error"] == "Not Found"
