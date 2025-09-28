# CLI Contract: biotools-annotate

## Command
`biotools-annotate run [OPTIONS]`

## Options
- `--from-date <SPAN>`: time window for new tools (e.g., `7d`, `30d`, `2025-09-01`). REQUIRED.
- `--min-score <FLOAT>`: minimum LS and relevance score for inclusion (default 0.6).
- `--limit <INT>`: max candidates to process (default unlimited).
- `--dry-run`: perform assessment and emit report only; do not write payload.
- `--output <PATH>`: path to write biotoolsSchema payload JSON (default `out/payload.json`).
- `--report <PATH>`: path to write JSONL assessment report (default `out/report.jsonl`).
- `--model <NAME>`: ollama model name (default from `OLLAMA_MODEL` or `llama3:8b`).
- `--concurrency <INT>`: max concurrent fetch/scrape jobs (default 8).
- `--verbose`: increase logging detail; `-q/--quiet` to reduce.
- `--help`: show usage.

## Behavior
- Reads candidates from Pub2Tools within the specified window; deduplicates by title/homepage.
- For each candidate, scrapes available pages (homepage/docs) to enrich evidence.
- Asks LLM to score `ls_score` and `relevance_score` in [0,1] with a short rationale.
- Improves annotations (description text, EDAM suggestions) while preserving source facts.
- Writes strict biotoolsSchema payload JSON containing only included candidates (scores ≥ threshold and evidence present) unless `--dry-run`.
- Always writes a JSONL report with full assessment details.

## Exit Codes
- `0`: success; outputs written per flags.
- `2`: invalid input or schema validation failure; no payload written.
- `3`: upstream errors (Pub2Tools unavailable) or scraping/LLM failures over tolerance.

## Examples
```
biotools-annotate run --from-date 7d --min-score 0.6 \
  --output out/payload.json --report out/report.jsonl

biotools-annotate run --from-date 2025-09-01 --dry-run
```

## Outputs
### Payload (payload.json)
Array of BioToolsEntry objects strictly conforming to biotoolsSchema version [NEEDS CLARIFICATION].

Minimal example element:
```
{
  "name": "ExampleTool",
  "description": "Annotates genomes with ...",
  "homepage": "https://example.org/tool",
  "publications": [{"doi": "10.1093/nar/gk..."}],
  "topic": ["http://edamontology.org/topic_0121"],
  "operation": ["http://edamontology.org/operation_0361"],
  "data": ["http://edamontology.org/data_2044"],
  "documentation": ["https://example.org/tool/docs"],
  "sourceCode": "https://github.com/org/tool"
}
```

### Report (report.jsonl)
One JSON object per candidate, including: candidate id/title, urls, scores, rationale, decision, reasons, errors (if any), timestamps, model and parameters.
