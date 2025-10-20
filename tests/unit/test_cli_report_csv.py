from __future__ import annotations

import csv
import gzip
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

import biotoolsllmannotate.assess.scorer as scorer_module
import biotoolsllmannotate.cli.run as run_module
from biotoolsllmannotate.cli.run import execute_run, write_report_csv
from biotoolsllmannotate.enrich import is_probable_publication_url
from biotoolsllmannotate.version import __version__


DOC_SUBSCORES = {
    "B1": 1.0,
    "B2": 1.0,
    "B3": 1.0,
    "B4": 0.5,
    "B5": 0.5,
}
DOC_SCORE_V2 = (
    2 * DOC_SUBSCORES["B1"]
    + DOC_SUBSCORES["B2"]
    + DOC_SUBSCORES["B3"]
    + DOC_SUBSCORES["B4"]
    + 2 * DOC_SUBSCORES["B5"]
) / 7


class DummyScorer:
    """Deterministic scorer used to stub LLM scoring calls."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    def score_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Return fixed scoring payload for the supplied candidate."""
        tool_name = candidate.get("title") or candidate.get("name") or ""
        homepage = ""
        raw_homepage = str(candidate.get("homepage") or "").strip()
        if raw_homepage and not is_probable_publication_url(raw_homepage):
            homepage = raw_homepage
        else:
            for raw in candidate.get("urls") or []:
                url = str(raw).strip()
                if not (url.startswith("http://") or url.startswith("https://")):
                    continue
                if is_probable_publication_url(url):
                    continue
                homepage = url
                break
        publication_ids = candidate.get("publication_ids", [])
        doc_subscores = DOC_SUBSCORES.copy()
        doc_score_v2 = DOC_SCORE_V2
        return {
            "tool_name": tool_name,
            "homepage": homepage,
            "publication_ids": publication_ids,
            "bio_score": 0.9,
            "bio_subscores": {
                "A1": 1.0,
                "A2": 1.0,
                "A3": 1.0,
                "A4": 1.0,
                "A5": 0.5,
            },
            "documentation_score": doc_score_v2,
            "documentation_subscores": doc_subscores,
            "concise_description": "Short summary.",
            "rationale": "Strong bioinformatics focus",
            "model": "llama3.2",
            "origin_types": [
                key for key in ["title", "description"] if candidate.get(key)
            ],
            "confidence_score": 0.9,
        }


def test_classify_candidate_requires_execution_path() -> None:
    scores = {
        "bio_score": 0.85,
        "bio_subscores": {"A4": 0.5},
        "documentation_score": 0.0,
        "documentation_subscores": {
            "B1": 1.0,
            "B2": 0.0,
            "B3": 1.0,
            "B4": 0.0,
            "B5": 1.0,
        },
    }
    decision = run_module.classify_candidate(  # type: ignore[attr-defined]
        scores,
        bio_thresholds=(0.5, 0.6),
        doc_thresholds=(0.3, 0.4),
        has_homepage=True,
    )
    assert decision == "review"
    assert scores["doc_score_v2"] == pytest.approx(5 / 7)
    assert scores["documentation_score_raw"] == pytest.approx(0.0)


def test_classify_candidate_requires_repro_anchor() -> None:
    scores = {
        "bio_score": 0.9,
        "bio_subscores": {"A4": 1.0},
        "documentation_score": 0.0,
        "documentation_subscores": {
            "B1": 1.0,
            "B2": 1.0,
            "B3": 0.0,
            "B4": 0.0,
            "B5": 1.0,
        },
    }
    decision = run_module.classify_candidate(  # type: ignore[attr-defined]
        scores,
        bio_thresholds=(0.5, 0.6),
        doc_thresholds=(0.3, 0.4),
        has_homepage=True,
    )
    assert decision == "review"
    assert scores["doc_score_v2"] == pytest.approx(5 / 7)
    assert scores["documentation_score_raw"] == pytest.approx(0.0)


def test_classify_candidate_add_when_requirements_met() -> None:
    scores = {
        "bio_score": 0.9,
        "bio_subscores": {"A4": 1.0},
        "documentation_score": 0.0,
        "documentation_subscores": {
            "B1": 1.0,
            "B2": 1.0,
            "B3": 0.5,
            "B4": 0.5,
            "B5": 1.0,
        },
    }
    decision = run_module.classify_candidate(  # type: ignore[attr-defined]
        scores,
        bio_thresholds=(0.5, 0.6),
        doc_thresholds=(0.3, 0.4),
        has_homepage=True,
    )
    assert decision == "add"
    assert scores["doc_score_v2"] == pytest.approx(6 / 7)


def test_write_report_csv(tmp_path: Path) -> None:
    """Write a CSV report with flattened scoring columns."""
    doc_subscores = DOC_SUBSCORES.copy()
    doc_score_v2 = DOC_SCORE_V2
    rows = [
        {
            "id": "tool-1",
            "title": "Tool One",
            "homepage": "https://example.org",
            "homepage_status": 404,
            "homepage_error": "HTTP 404",
            "publication_ids": ["pmid:12345"],
            "include": "add",
            "in_biotools_name": True,
            "in_biotools": True,
            "scores": {
                "bio_score": 0.9,
                "bio_subscores": {
                    "A1": 1.0,
                    "A2": 1.0,
                    "A3": 1.0,
                    "A4": 1.0,
                    "A5": 0.5,
                },
                "documentation_score": DOC_SCORE_V2,
                "documentation_subscores": DOC_SUBSCORES.copy(),
                "concise_description": "Short summary.",
                "tool_name": "Tool One",
                "rationale": "Strong bioinformatics focus",
                "model": "llama3.2",
                "origin_types": ["title", "description"],
                "confidence_score": 0.9,
            },
        }
    ]

    csv_path = tmp_path / "report.csv"
    write_report_csv(csv_path, rows)

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)

    assert len(data) == 1
    row = data[0]
    assert row["id"] == "tool-1"
    assert row["include"] == "add"
    assert row["bio_score"] == "0.9"
    assert row["bio_A1"] == "1.0"
    assert row["bio_A5"] == "0.5"
    assert float(row["documentation_score"]) == pytest.approx(doc_score_v2)
    assert row["doc_B4"] == "0.5"
    assert row["confidence_score"] == "0.9"
    assert row["concise_description"] == "Short summary."
    assert row["tool_name"] == "Tool One"
    assert row["origin_types"] == "title, description"
    assert row["publication_ids"] == "pmid:12345"
    assert row["in_biotools_name"] == "True"
    assert row["in_biotools"] == "True"
    assert row["homepage_status"] == "404"
    assert row["homepage_error"] == "HTTP 404"


def test_execute_run_emits_csv_with_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute run produces CSV with identifier columns populated."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )
    monkeypatch.setattr(
        run_module,
        "scrape_homepage_metadata",
        lambda candidate, config=None, logger=None: candidate.update(
            {
                "homepage_status": 200,
                "homepage_error": None,
                "homepage_scraped": True,
            }
        ),
    )

    candidates = [
        {
            "tool_id": "tool-123",
            "name": "Example Tool",
            "urls": ["https://example.org"],
            "description": "A sample entry",
            "publication": [{"pmid": "12345"}],
        }
    ]
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.5, 0.6),
        doc_thresholds=(0.5, 0.6),
        limit=None,
        dry_run=True,
        model="llama3.2",
        concurrency=1,
        input_path=str(input_path),
        offline=False,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    report_path = run_dir / "reports" / "assessment.jsonl"
    csv_path = report_path.with_suffix(".csv")
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)

    assert len(data) == 1
    row = data[0]
    assert row["id"] == "tool-123"
    assert row["title"] == "Example Tool"
    assert row["homepage"] == "https://example.org"
    assert row["tool_name"] == "Example Tool"
    assert row["in_biotools_name"] == ""
    assert row["in_biotools"] == ""
    assert row["confidence_score"] == "0.9"
    assert "homepage_status" in row
    assert "homepage_error" in row


def test_execute_run_marks_existing_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing registry entries are marked accordingly in output."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    registry_path = registry_dir / "biotools.json"
    registry_path.write_text(
        json.dumps(
            [
                {
                    "name": "Registry Tool",
                    "homepage": "https://registry.example",
                    "biotoolsID": "registrytool",
                }
            ]
        ),
        encoding="utf-8",
    )

    candidates = [
        {
            "title": "Registry Tool",
            "urls": ["https://registry.example"],
            "description": "Catalogued tool",
        }
    ]
    input_path = input_dir / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.5, 0.6),
        doc_thresholds=(0.5, 0.6),
        dry_run=True,
        concurrency=1,
        input_path=str(input_path),
        registry_path=str(registry_path),
        offline=True,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    report_path = run_dir / "reports" / "assessment.jsonl"
    csv_path = report_path.with_suffix(".csv")
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)

    assert len(data) == 1
    row = data[0]
    assert row["in_biotools"] == "True"
    assert row["in_biotools_name"] == "True"
    assert row["confidence_score"] == "0.6"
    assert "homepage_status" in row
    assert "homepage_error" in row


def test_execute_run_filters_publication_homepage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline drops publication-style homepages when no alternative exists."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )

    candidates = [
        {
            "tool_id": "pubmed-1",
            "title": "PubMed Tool",
            "homepage": "https://pubmed.ncbi.nlm.nih.gov/123456/",
            "urls": [
                "https://pubmed.ncbi.nlm.nih.gov/123456/",
                "https://link.springer.com/article/10.1000/example",
            ],
            "description": "Publication-first candidate",
        }
    ]

    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    execute_run(
        from_date="7d",
        to_date=None,
    bio_thresholds=(0.5, 0.6),
    doc_thresholds=(0.5, 0.6),
        limit=None,
        dry_run=True,
        concurrency=1,
        input_path=str(input_path),
        offline=False,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    report_path = run_dir / "reports" / "assessment.jsonl"
    csv_path = report_path.with_suffix(".csv")
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)

    assert len(data) == 1
    row = data[0]
    assert row["homepage"] == ""
    assert row["include"] == "do_not_add"


def test_execute_run_publication_only_zero_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publication-only candidates bypass LLM and receive rule-based zero scores."""

    class FailScorer:
        client = None

        def __init__(
            self, model: str | None = None, config: dict[str, Any] | None = None
        ) -> None:
            self.model = model
            self.config = config

        def score_candidate(
            self, candidate: dict[str, Any]
        ) -> dict[str, Any]:  # pragma: no cover - should not run
            raise AssertionError(
                "LLM scorer should not run for publication-only candidates"
            )

    monkeypatch.setattr(
        scorer_module,
        "Scorer",
        lambda model=None, config=None: FailScorer(model, config),
    )

    candidates = [
        {
            "tool_id": "pubmed-2",
            "title": "PubMed Only Tool",
            "homepage": "https://pubmed.ncbi.nlm.nih.gov/987654/",
            "urls": [
                "https://pubmed.ncbi.nlm.nih.gov/987654/",
                "https://doi.org/10.1000/example",
            ],
            "publication": [{"pmid": "987654"}],
        }
    ]

    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.6, 0.6),
        doc_thresholds=(0.6, 0.6),
        limit=None,
        dry_run=True,
        model="llama3.2",
        concurrency=1,
        input_path=str(input_path),
        offline=False,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    report_path = run_dir / "reports" / "assessment.jsonl"
    lines = report_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    decision = json.loads(lines[0])

    assert decision["homepage"] == ""
    assert decision["include"] == "do_not_add"
    assert decision["scores"]["model"] == "rule:no-homepage"
    assert decision["scores"]["bio_score"] == 0.0
    assert decision["scores"]["documentation_score"] == 0.0
    assert decision["scores"]["model_params"]["reason"] == "publication_url"
    assert decision["scores"]["publication_ids"] == ["pmid:987654"]
    assert decision.get("in_biotools_name") is None


def test_execute_run_payload_strips_null_fields(tmp_path: Path) -> None:
    """Payload JSON excludes any fields whose value was null."""

    candidates = [
        {
            "tool_id": "null-tags",
            "name": "Null Tags Tool",
            "urls": [
                "https://nulltags.example.org",
                "https://docs.nulltags.example.org",
            ],
            "description": "Tool with sparse tags",
            "tags": ["genomics", None, ""],
        }
    ]
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.0, 0.0),
        doc_thresholds=(0.0, 0.0),
        dry_run=False,
        concurrency=1,
        input_path=str(input_path),
        offline=True,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    payload_path = run_dir / "exports" / "biotools_payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    def _contains_none(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, dict):
            return any(_contains_none(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return any(_contains_none(item) for item in value)
        return False

    assert isinstance(payload, list) and payload
    assert not _contains_none(payload)


def test_execute_run_writes_updated_entries_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute run writes refreshed entries JSON files."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )
    monkeypatch.setattr(
        run_module,
        "scrape_homepage_metadata",
        lambda candidate, config=None, logger=None: candidate.update(
            {
                "homepage_status": 200,
                "homepage_error": None,
                "homepage_scraped": True,
            }
        ),
    )

    candidates = [
        {
            "title": "Example Tool",
            "description": "Original description",
            "homepage": "https://original.example.org",
            "urls": ["https://example.org"],
            "publication": [{"pmcid": "PMC1234567"}],
            "documentation": [{"url": "https://example.org/docs", "type": ["Manual"]}],
        }
    ]
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.5, 0.6),
        doc_thresholds=(0.5, 0.6),
        limit=None,
        dry_run=False,
        model="llama3.2",
        concurrency=1,
        input_path=str(input_path),
        offline=False,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    payload_path = run_dir / "exports" / "biotools_payload.json"
    updated_path = run_dir / "exports" / "biotools_entries.json"

    assert payload_path.exists()
    assert updated_path.exists()
    data = json.loads(updated_path.read_text())
    assert data["version"] == __version__
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["name"] == "Example Tool"
    assert entry["homepage"] == "https://original.example.org"
    assert entry["description"] == "Short summary."
    assert entry.get("publication")


def test_execute_run_logs_score_duration(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Execute run logs timing metrics for scoring."""
    candidates = [
        {
            "title": "Timing Tool",
            "urls": ["https://timing.example"],
            "description": "Example candidate",
        }
    ]
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.5, 0.6),
        doc_thresholds=(0.5, 0.6),
        limit=None,
        dry_run=True,
        concurrency=1,
        input_path=str(input_path),
        offline=True,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    captured = capfd.readouterr()
    assert "score_elapsed_seconds" in captured.out


def test_resume_from_enriched_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume pipeline from enriched candidate cache."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )

    candidates = [
        {
            "title": "CacheTool",
            "description": "Cached tool",
            "urls": ["https://cache.example"],
            "publication": [{"pmid": "999"}],
        }
    ]
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    # First run saves the enriched candidates
    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.6, 0.6),
        doc_thresholds=(0.6, 0.6),
        limit=None,
        dry_run=True,
        model="llama3.2",
        concurrency=1,
        input_path=str(input_path),
        offline=True,
        show_progress=False,
        output_root=tmp_path / "out",
    )
    out_dir = tmp_path / "out"
    run_dir = out_dir / "custom_tool_set"
    assert run_dir.exists()
    cache_path = run_dir / "cache" / "enriched_candidates.json.gz"
    assert cache_path.exists()

    # Resume from cache without providing input path
    execute_run(
        from_date="7d",
        to_date=None,
        bio_thresholds=(0.6, 0.6),
        doc_thresholds=(0.6, 0.6),
        limit=None,
        dry_run=False,
        resume_from_enriched=True,
        model="llama3.2",
        concurrency=1,
        input_path=None,
        offline=True,
        show_progress=False,
        output_root=tmp_path / "out",
    )
    payload_path = run_dir / "exports" / "biotools_payload.json"
    assert payload_path.exists()


def test_resume_from_pub2tools_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume pipeline using saved pub2tools export."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )

    out_root = tmp_path / "out"
    range_dir = out_root / "range_2024-01-01_to_2024-01-31"
    export_dir = range_dir / "pub2tools"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / "to_biotools.json"
    export_path.write_text(
        json.dumps(
            [
                {
                    "title": "Bioinformatics Resume Tool",
                    "description": "Cached via pub2tools",
                    "urls": ["https://resume.example"],
                    "publication": [{"pmid": "777"}],
                    "tags": ["bioinformatics"],
                }
            ]
        ),
        encoding="utf-8",
    )

    execute_run(
        from_date="2024-01-01",
        to_date="2024-01-31",
        bio_thresholds=(0.6, 0.6),
        doc_thresholds=(0.6, 0.6),
        dry_run=False,
        resume_from_pub2tools=True,
        offline=True,
        show_progress=False,
        model="llama3.2",
        concurrency=1,
        output_root=out_root,
    )

    payload_path = range_dir / "exports" / "biotools_payload.json"
    assert payload_path.exists()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["name"] == "Bioinformatics Resume Tool"


def test_resume_from_pub2tools_ignores_other_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume from pub2tools uses only matching date ranges."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )

    out_root = tmp_path / "out"
    target_label = "range_2024-05-01_to_2024-05-31"
    target_dir = out_root / target_label
    other_dir = out_root / "range_2024-04-01_to_2024-04-30"

    target_export = target_dir / "pub2tools"
    target_export.mkdir(parents=True, exist_ok=True)
    target_path = target_export / "to_biotools.json"
    target_path.write_text(
        json.dumps(
            [
                {
                    "title": "Target Candidate",
                    "description": "Correct range",
                    "urls": ["https://target.example"],
                    "publication": [{"pmid": "999"}],
                    "tags": ["bioinformatics"],
                }
            ]
        ),
        encoding="utf-8",
    )
    past_time = time.time() - 3600
    os.utime(target_path, (past_time, past_time))

    other_export = other_dir / "pub2tools"
    other_export.mkdir(parents=True, exist_ok=True)
    other_path = other_export / "to_biotools.json"
    other_path.write_text(
        json.dumps(
            [
                {
                    "title": "Other Candidate",
                    "description": "Different range",
                    "urls": ["https://other.example"],
                    "publication": [{"pmid": "111"}],
                    "tags": ["bioinformatics"],
                }
            ]
        ),
        encoding="utf-8",
    )
    recent_time = time.time()
    os.utime(other_path, (recent_time, recent_time))

    execute_run(
        from_date="2024-05-01",
        to_date="2024-05-31",
        bio_thresholds=(0.6, 0.6),
        doc_thresholds=(0.6, 0.6),
        dry_run=False,
        resume_from_pub2tools=True,
        offline=True,
        show_progress=False,
        model="llama3.2",
        concurrency=1,
        output_root=out_root,
    )

    payload_path = target_dir / "exports" / "biotools_payload.json"
    assert payload_path.exists()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["name"] == "Target Candidate"


def test_resume_from_scoring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resume pipeline from scoring artifacts."""
    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )

    out_root = tmp_path / "out"
    range_dir = out_root / "range_2024-02-01_to_2024-02-28"
    cache_dir = range_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "enriched_candidates.json.gz"

    enriched_candidates = [
        {
            "tool_id": "resume-stage",
            "title": "Resume Stage Tool",
            "description": "Cached stage tool",
            "urls": ["https://resume-stage.example"],
            "publication": [{"pmid": "888"}],
            "tags": ["bioinformatics"],
        }
    ]
    with gzip.open(cache_path, "wt", encoding="utf-8") as fh:
        json.dump(enriched_candidates, fh)

    report_dir = range_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "assessment.jsonl"
    cached_rows = [
        {
            "id": "resume-stage",
            "title": "Resume Stage Tool",
            "homepage": "",
            "scores": {
                "tool_name": "Resume Stage Tool",
                "homepage": "https://resume-stage.example",
                "publication_ids": ["pmid:888"],
                "bio_score": 0.9,
                "bio_subscores": {
                    "A1": 1.0,
                    "A2": 1.0,
                    "A3": 1.0,
                    "A4": 1.0,
                    "A5": 0.5,
                },
                "documentation_score": DOC_SCORE_V2,
                "documentation_subscores": DOC_SUBSCORES.copy(),
                "concise_description": "Short summary.",
                "confidence_score": 0.4,
            },
            "include": "do_not_add",
            "decision": "do_not_add",
        }
    ]
    report_path.write_text(
        "\n".join(json.dumps(row) for row in cached_rows) + "\n",
        encoding="utf-8",
    )

    execute_run(
        from_date="2024-02-01",
        to_date="2024-02-28",
        bio_thresholds=(0.6, 0.6),
        doc_thresholds=(0.6, 0.6),
        dry_run=False,
        resume_from_enriched=True,
        resume_from_scoring=True,
        offline=True,
        show_progress=False,
        model="llama3.2",
        concurrency=1,
        output_root=out_root,
    )

    payload_path = range_dir / "exports" / "biotools_payload.json"
    assert payload_path.exists()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["name"] == "Resume Stage Tool"

    report_lines = [
        json.loads(line)
        for line in report_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(report_lines) == 1
    assert report_lines[0]["include"] == "add"
