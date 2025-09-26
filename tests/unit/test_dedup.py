import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from biotoolsllmannotate.ingest.dedup import deduplicate_candidates


def test_deduplicate_candidates_basic():
    candidates = [
        {"title": "GeneAnnotator", "homepage": "https://ex.org/a"},
        {"title": "GeneAnnotator", "homepage": "https://ex.org/a"},
        {"title": "GeneAnnotator", "homepage": "https://ex.org/b"},
        {"title": "GENEANNOTATOR", "homepage": "https://ex.org/a"},
        {"title": "OtherTool", "homepage": "https://ex.org/c"},
    ]
    deduped = deduplicate_candidates(candidates)
    assert len(deduped) == 3
    titles = set(c["title"].lower() for c in deduped)
    assert "geneannotator" in titles
    assert "othertool" in titles
    homepages = set(c["homepage"] for c in deduped)
    assert "https://ex.org/a" in homepages
    assert "https://ex.org/b" in homepages
    assert "https://ex.org/c" in homepages
