# Phase 0: Outline & Research — Pub2Tools-based bio.tools Annotation CLI

## Decisions
- Pub2Tools source: Use official Pub2Tools outputs for “new tools” within a time window. Default window `--from-date 7d` (ISO-8601 timestamp derived at runtime).
- LLM: Use local `ollama` with a lightweight instruct model (default `llama3:8b`). Temperature 0.1, top_p 0.9, max tokens tuned to short rationales. Deterministic seed when supported.
- Evidence rules: Include candidates only when both scores ≥ threshold (default 0.6 LS, 0.6 relevance) and at least one evidence link (homepage or docs).
- Schema validation: Build pydantic models mirroring biotoolsSchema; validate every UploadPayload before writing.
- Outputs: Two files per run: `out/payload.json` (array for bio.tools upload) and `out/report.jsonl` (one line per candidate with inputs, scores, rationale, decision).

## Unknowns (NEEDS CLARIFICATION)
- Pub2Tools access: exact endpoint/export format and authentication if any.
- biotoolsSchema version and required minimal fields for new entries.
- Upload process: is direct upload required later, or only JSON generation here?
- Expected throughput (candidates/run) to size batch and concurrency.

## Rationale
- Local `ollama` avoids external dependencies and aligns with reproducibility and cost control.
- Pydantic models provide strict validation against schema, ensuring upload safety.
- Separate report enables auditability and human curation.

## Alternatives Considered
- Cloud LLMs (OpenAI/Anthropic): rejected for offline constraints and cost.
- Scrapy for crawling: overkill for single-page evidence; choose requests + parser.
- Single combined output: rejected; separates concerns poorly vs. split payload/report.

## Open Questions to Resolve Before Implementation
1. Confirm Pub2Tools query mechanics and “new” definition (last week vs. since last run).
2. Finalize schema fields: minimum viable bio.tools entry (name, description, homepage, EDAM?).
3. Choose default model in `ollama` based on local availability/performance.
4. Define retry limits and backoff for HTTP and LLM calls.
