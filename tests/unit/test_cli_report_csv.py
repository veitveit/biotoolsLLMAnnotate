import csv
import gzip
import json
import os
import time


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
    assert row["in_biotools"] == "True"


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

    execute_run(
        from_date="7d",
        to_date=None,
        min_bio_score=0.6,
        min_doc_score=0.6,
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
    time_period_dirs = list(out_dir.glob("range_*"))
    assert len(time_period_dirs) == 1
    report_path = time_period_dirs[0] / "reports" / "assessment.jsonl"
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
    assert row["in_biotools"] == ""


def test_execute_run_marks_existing_registry(tmp_path, monkeypatch):
    from biotoolsllmannotate.cli.run import execute_run
    import biotoolsllmannotate.assess.scorer as scorer_module
    from biotoolsllmannotate.config import DEFAULT_CONFIG_YAML

    monkeypatch.setattr(
        scorer_module, "Scorer", lambda model=None, config=None: DummyScorer(model)
    )

    input_dir = tmp_path / "input"
    input_dir.mkdir()

    registry_path = input_dir / "biotools.json"
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
        min_bio_score=0.6,
        min_doc_score=0.6,
        dry_run=True,
        concurrency=1,
        input_path=str(input_path),
        offline=True,
        show_progress=False,
        output_root=tmp_path / "out",
    )

    out_dir = tmp_path / "out"
    time_period_dirs = list(out_dir.glob("range_*"))
    assert len(time_period_dirs) == 1
    report_path = time_period_dirs[0] / "reports" / "assessment.jsonl"
    csv_path = report_path.with_suffix(".csv")
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)

    assert len(data) == 1
    row = data[0]
    assert row["in_biotools"] == "True"


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

    execute_run(
        from_date="7d",
        to_date=None,
        min_bio_score=0.6,
        min_doc_score=0.6,
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
    time_period_dirs = list(out_dir.glob("range_*"))
    assert len(time_period_dirs) == 1
    run_dir = time_period_dirs[0]
    payload_path = run_dir / "exports" / "biotools_payload.json"
    updated_path = run_dir / "exports" / "biotools_entries.json"

    assert payload_path.exists()
    assert updated_path.exists()
    data = json.loads(updated_path.read_text())
    from biotoolsllmannotate.version import __version__

    assert data["version"] == __version__
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

    execute_run(
        from_date="7d",
        to_date=None,
        min_bio_score=0.6,
        min_doc_score=0.6,
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
    input_path = tmp_path / "candidates.json"
    input_path.write_text(json.dumps(candidates), encoding="utf-8")

    # First run saves the enriched candidates
    execute_run(
        from_date="7d",
        to_date=None,
        min_bio_score=0.6,
        min_doc_score=0.6,
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
    time_period_dirs = list(out_dir.glob("range_*"))
    assert len(time_period_dirs) == 1
    run_dir = time_period_dirs[0]
    cache_path = run_dir / "cache" / "enriched_candidates.json.gz"
    assert cache_path.exists()

    # Resume from cache without providing input path
    execute_run(
        from_date="7d",
        to_date=None,
        min_bio_score=0.6,
        min_doc_score=0.6,
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


def test_resume_from_pub2tools_export(tmp_path, monkeypatch):
    from biotoolsllmannotate.cli.run import execute_run
    import biotoolsllmannotate.assess.scorer as scorer_module

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
        min_bio_score=0.6,
        min_doc_score=0.6,
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


def test_resume_from_pub2tools_ignores_other_ranges(tmp_path, monkeypatch):
    from biotoolsllmannotate.cli.run import execute_run
    import biotoolsllmannotate.assess.scorer as scorer_module

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
        min_bio_score=0.6,
        min_doc_score=0.6,
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


def test_resume_from_scoring(tmp_path, monkeypatch):
    from biotoolsllmannotate.cli.run import execute_run
    import biotoolsllmannotate.assess.scorer as scorer_module

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
                "documentation_score": 0.8,
                "documentation_subscores": {
                    "B1": 1.0,
                    "B2": 1.0,
                    "B3": 1.0,
                    "B4": 0.5,
                    "B5": 0.5,
                },
                "concise_description": "Short summary.",
            },
            "include": False,
        }
    ]
    report_path.write_text(
        "\n".join(json.dumps(row) for row in cached_rows) + "\n",
        encoding="utf-8",
    )

    execute_run(
        from_date="2024-02-01",
        to_date="2024-02-28",
        min_bio_score=0.6,
        min_doc_score=0.6,
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
    assert report_lines[0]["include"] is True
