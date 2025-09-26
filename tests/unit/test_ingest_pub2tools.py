from datetime import UTC, datetime, timedelta


def test_filter_and_dedup_candidates(tmp_path):
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
