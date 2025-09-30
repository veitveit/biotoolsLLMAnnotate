# BioToolsLLMAnnotate

CLI tools for discovering, enriching, and annotating bio.tools entries with help from Pub2Tools, heuristic scraping, and Ollama-based scoring.

## Table of Contents
- [Overview](#overview)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
  - [Core settings](#core-settings)
  - [Coming soon: Pub2Tools guide](#coming-soon-pub2tools-guide)
  - [Coming soon: Europe PMC tips](#coming-soon-europe-pmc-tips)
- [Running the Pipeline](#running-the-pipeline)
- [Generated Outputs](#generated-outputs)
- [Resume & Caching](#resume--caching)
- [Troubleshooting & Tips](#troubleshooting--tips)
- [Development](#development)
- [License](#license)

## Overview
- Fetch candidate records from Pub2Tools exports or existing JSON files.
- Enrich candidates with homepage metadata, documentation links, repositories, and publication context.
- Score bioinformatics relevance and documentation quality using an Ollama model.
- Produce strict biotoolsSchema payloads plus human-readable assessment reports.
- Resume any stage (gather, enrich, score) using cached artifacts to accelerate iteration.

## Installation
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
ollama pull llama3.2  # optional, only needed for LLM scoring
```

> Need defaults? Generate a starter configuration with:
> ```bash
> python -m biotoolsllmannotate --write-default-config
> ```

## Quick Start
```bash
# Dry-run against sample data (no network calls)
python -m biotoolsllmannotate --input tests/fixtures/pub2tools/sample.json --dry-run

# Fetch fresh candidates from the last 7 days and score them
python -m biotoolsllmannotate --from-date 7d --min-score 0.6

# Re-run only the scoring step with cached enrichment
python -m biotoolsllmannotate --resume-from-enriched --resume-from-scoring --dry-run
```

## Configuration
Configuration is YAML-driven. The CLI loads `config.yaml` from the project root by default and falls back to internal defaults when absent. All placeholders marked `__VERSION__` resolve to the installed package version at runtime.

### Core settings
| Purpose | Config key | CLI flag | Notes |
| --- | --- | --- | --- |
| Input source | `pipeline.input_path` | `--input PATH` | Prefer a local JSON export instead of running Pub2Tools |
| Date range | `pipeline.from_date`, `pipeline.to_date` | `--from-date`, `--to-date` | Accepts relative windows like `7d` or ISO dates |
| Thresholds | `pipeline.min_bio_score`, `pipeline.min_documentation_score` | `--min-bio-score`, `--min-doc-score` | Set both via legacy `--min-score` if desired |
| Offline mode | `pipeline.offline` | `--offline` | Disables homepage scraping and Europe PMC enrichment |
| Ollama model | `ollama.model` | `--model` | Defaults to `llama3.2`; override per run |
| Concurrency | `ollama.concurrency` | `--concurrency` | Controls parallel scoring workers |
| Logging | `logging.level`, `logging.file` | `--verbose`, `--quiet` | Flags override log level; file path set in config |

### Coming soon: Pub2Tools guide
Detailed guidance for configuring Pub2Tools (wrapper usage, environment variables, and advanced fetch options) will be documented here in an upcoming update.

### Coming soon: Europe PMC tips
A focused walkthrough for Europe PMC enrichment settings—including performance trade-offs and offline strategies—will be published here soon.

## Running the Pipeline
Common invocations:
```bash
# Custom date window
python -m biotoolsllmannotate --from-date 2024-01-01 --to-date 2024-03-31

# Offline mode (no network scraping or Europe PMC requests)
python -m biotoolsllmannotate --offline

# Limit the number of candidates processed
python -m biotoolsllmannotate --limit 25

# Point to a specific config file
python -m biotoolsllmannotate --config myconfig.yaml
```

Use `python -m biotoolsllmannotate --help` to explore all available flags, including concurrency settings, progress display, and resume options.

## Generated Outputs
Each run writes artifacts to `out/<range_start>_to_<range_end>/...`:

| Path | Description |
| --- | --- |
| `exports/biotools_payload.json` | biotoolsSchema-compliant payload ready for upload |
| `exports/biotools_entries.json` | Full entries including enriched metadata |
| `reports/assessment.jsonl` | Line-delimited scoring results (bio score, doc score, rationale) |
| `reports/assessment.csv` | Spreadsheet-friendly summary of the JSONL file |
| `cache/enriched_candidates.json.gz` | Cached candidates after enrichment for quick resumes |
| `logs/ollama.log` | Append-only log of all LLM scoring prompts and responses |
| `config.generated.yaml` or `<original-config>.yaml` | Snapshot of the configuration used for the run |

## Resume & Caching
- `--resume-from-pub2tools`: Reuse the latest `to_biotools.json` export for the active time range.
- `--resume-from-enriched`: Skip ingestion and reuse `cache/enriched_candidates.json.gz`.
- `--resume-from-scoring`: Reapply thresholds to a previous `assessment.jsonl` without invoking the LLM.

Combine the flags to iterate quickly on scoring thresholds and payload exports without repeating expensive steps.

## Troubleshooting & Tips
- Use `--offline` when working without network access; the pipeline disables homepage scraping and publication enrichment automatically.
- To inspect what the model saw, open the most recent entries in `reports/assessment.jsonl` or the CSV export.
- Health checks against the Ollama host run before scoring. Failures fall back to heuristics and are summarized in the run footer.
- Adjust logging verbosity with `--quiet` or `--verbose` as needed.

## Development
- Lint: `ruff check .`
- Format: `black .`
- Type check: `mypy src`
- Tests: `pytest -q`
- Coverage: `pytest --cov=biotoolsllmannotate --cov-report=term-missing`

## License
MIT
