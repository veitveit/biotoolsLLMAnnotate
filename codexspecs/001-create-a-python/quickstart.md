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
# Fetch, assess, improve, and emit payload + report
biotools-annotate run --from-date 7d --min-score 0.6 \
  --output out/payload.json --report out/report.jsonl

# Dry run (no payload written)
biotools-annotate run --from-date 1w --dry-run --report out/report.jsonl

# Increase strictness and limit batch size
biotools-annotate run --from-date 30d --min-score 0.8 --limit 200
```

## Output
- `out/payload.json`: Strict biotoolsSchema JSON array for upload
- `out/report.jsonl`: Per-candidate line with inputs, scores, rationale, decision

## Notes
- Network access may be required for Pub2Tools and page scraping; tests mock I/O.
- Set environment var `OLLAMA_MODEL=llama3:8b` to override model.
- Validation errors block writing payload; see report for failures.
