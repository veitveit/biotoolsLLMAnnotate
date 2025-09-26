# Quickstart: Pub2Tools-based bio.tools Annotation CLI

## Prerequisites
- Python 3.11+
- `ollama` installed and running locally
  - Install: https://ollama.ai
  - Pull model: `ollama pull llama3:8b`

## Setup
```
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## Example Usage
```
# Run annotation pipeline on recent candidates
biotools-annotate run --since 7d --min-score 0.6 \
  --output out/payload.json --report out/report.jsonl

# Dry run (no payload written)
biotools-annotate run --since 1w --dry-run --report out/report.jsonl

# Increase strictness and limit batch size
biotools-annotate run --since 30d --min-score 0.8 --limit 200

# Use quiet or verbose output
biotools-annotate run --quiet
biotools-annotate run --verbose

# Specify input file or Pub2Tools output
biotools-annotate run --input tests/fixtures/pub2tools/sample.json
biotools-annotate run --p2t-out path/to/pub2tools.json

# Disable web/repo fetching (offline mode)
biotools-annotate run --offline

# Show help and exit codes
biotools-annotate run --help
```

## Pub2Tools Workflow Example
```
# 1. Run Pub2Tools for a given month
bin/pub2tools run_month_all 2025-08

# 2. Convert output to biotools format
bin/pub2tools load_to_biotools_json out/pub2tools_2025-08.json out/to_biotools.json

# 3. Annotate using the CLI
biotools-annotate run --input out/to_biotools.json --output out/payload.json --report out/report.jsonl
```

## Output
- `out/payload.json`: Strict biotoolsSchema JSON array for upload
- `out/report.jsonl`: Per-candidate line with inputs, scores, rationale, decision

## Evidence Policy
- When candidate information is uncertain, the pipeline attempts to consult:
  - The candidate's website
  - Documentation links
  - Repository metadata (e.g., README)
- You can disable web/repo evidence gathering with `--offline`.
- Evidence and rationale for each candidate appear in the `out/report.jsonl` file, including which sources were used and any uncertainty flags (e.g., `needs_review`).

## Notes
- Network access may be required for Pub2Tools and page scraping; tests mock I/O.
- Set environment var `OLLAMA_MODEL=llama3:8b` to override model.
- Validation errors block writing payload; see report for failures.
- Exit codes: 0 (success), 2 (schema validation failed), 3 (unhandled error)
