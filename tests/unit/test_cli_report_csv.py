import csv
import json


class DummyScorer:
    def __init__(self, model=None):
        self.model = model

    def score_candidate(self, candidate):
        tool_name = candidate.get("title") or candidate.get("name") or ""
        homepage = candidate.get("homepage") or next(
            (
                str(u)
                for u in (candidate.get("urls") or [])
                if str(u).startswith("http")
            ),
            "",
        )
        publication_ids = candidate.get("publication_ids", [])
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
            "documentation_score": 0.8,
            "documentation_subscores": {
                "B1": 1.0,
                "B2": 1.0,
                "B3": 1.0,
                "B4": 0.5,
                "B5": 0.5,
            },
            "concise_description": "Short summary.",
            "rationale": "Strong bioinformatics focus",
            "model": "llama3.2",
            "origin_types": [
                key for key in ["title", "description"] if candidate.get(key)
            ],
        }


def test_write_report_csv(tmp_path):
    from biotoolsllmannotate.cli.run import write_report_csv

    rows = [
        {
            "id": "tool-1",
            "title": "Tool One",
            "homepage": "https://example.org",
            "publication_ids": ["pmid:12345"],
            "include": True,
            "scores": {
                "bio_score": 0.9,
                "bio_subscores": {
                    "A1": 1.0,
                    "A2": 1.0,
                    "A3": 1.0,
                    "A4": 1.0,
                    "A5": 0.5,
                },
                "documentation_score": 0.8,
                "documentation_subscores": {
                    "B1": 1.0,
                    "B2": 1.0,
                    "B3": 1.0,
                    "B4": 0.5,
                    "B5": 0.5,
                },
                "concise_description": "Short summary.",
                "tool_name": "Tool One",
                "rationale": "Strong bioinformatics focus",
                "model": "llama3.2",
                "origin_types": ["title", "description"],
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
    assert row["include"] == "True"
    assert row["bio_score"] == "0.9"
    assert row["bio_A1"] == "1.0"
    assert row["bio_A5"] == "0.5"
    assert row["documentation_score"] == "0.8"
    assert row["doc_B4"] == "0.5"
    assert row["concise_description"] == "Short summary."
    assert row["tool_name"] == "Tool One"
    assert row["origin_types"] == "title, description"
    assert row["publication_ids"] == "pmid:12345"


def test_execute_run_emits_csv_with_identifiers(tmp_path, monkeypatch):
    from biotoolsllmannotate.cli.run import execute_run
    import biotoolsllmannotate.assess.scorer as scorer_module

    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
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

    report_path = tmp_path / "report.jsonl"
    output_path = tmp_path / "payload.json"

    execute_run(
        from_date="7d",
        to_date=None,
        min_score=0.6,
        limit=None,
        dry_run=True,
        output=output_path,
        report=report_path,
        model="llama3.2",
        concurrency=1,
        input_path=str(input_path),
        offline=False,
    )

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


def test_execute_run_writes_updated_entries_file(tmp_path, monkeypatch):
    from biotoolsllmannotate.cli.run import execute_run
    import biotoolsllmannotate.assess.scorer as scorer_module

    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
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

    payload_path = tmp_path / "payload.json"
    report_path = tmp_path / "report.jsonl"
    updated_path = tmp_path / "updated.json"

    execute_run(
        from_date="7d",
        to_date=None,
        min_score=0.6,
        limit=None,
        dry_run=False,
        output=payload_path,
        report=report_path,
        updated_entries=updated_path,
        model="llama3.2",
        concurrency=1,
        input_path=str(input_path),
        offline=False,
        show_progress=False,
    )

    assert payload_path.exists()
    assert updated_path.exists()
    data = json.loads(updated_path.read_text())
    assert data["version"] == "0.9.1"
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["name"] == "Example Tool"
    assert entry["homepage"] == "https://original.example.org"
    assert entry["description"] == "Short summary."
    assert entry.get("publication")


def test_execute_run_logs_score_duration(tmp_path, capfd):
    from biotoolsllmannotate.cli.run import execute_run

    candidates = [
        {
            "title": "Timing Tool",
            "urls": ["https://timing.example"],
            "description": "Example candidate",
        }
    ]
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    payload_path = tmp_path / "payload.json"
    report_path = tmp_path / "report.jsonl"

    execute_run(
        from_date="7d",
        to_date=None,
        min_score=0.6,
        limit=None,
        dry_run=True,
        output=payload_path,
        report=report_path,
        concurrency=1,
        input_path=str(input_path),
        offline=True,
        show_progress=False,
    )

    captured = capfd.readouterr()
    assert "score_elapsed_seconds" in captured.out


def test_resume_from_enriched_cache(tmp_path, monkeypatch):
    from biotoolsllmannotate.cli.run import execute_run
    import biotoolsllmannotate.assess.scorer as scorer_module

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
    cache_path = tmp_path / "enriched.json.gz"
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    # First run saves the enriched candidates
    execute_run(
        from_date="7d",
        to_date=None,
        min_score=0.6,
        limit=None,
        dry_run=True,
        output=tmp_path / "payload1.json",
        report=tmp_path / "report1.jsonl",
        enriched_cache=cache_path,
        model="llama3.2",
        concurrency=1,
        input_path=str(input_path),
        offline=True,
        show_progress=False,
    )
    assert cache_path.exists()

    # Resume from cache without providing input path
    execute_run(
        from_date="7d",
        to_date=None,
        min_score=0.6,
        limit=None,
        dry_run=False,
        output=tmp_path / "payload2.json",
        report=tmp_path / "report2.jsonl",
        enriched_cache=cache_path,
        resume_from_enriched=True,
        model="llama3.2",
        concurrency=1,
        input_path=None,
        offline=True,
        show_progress=False,
    )
    assert (tmp_path / "payload2.json").exists()
