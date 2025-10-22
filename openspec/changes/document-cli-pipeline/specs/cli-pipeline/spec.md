## ADDED Requirements
### Requirement: Pipeline Stage Progression
The CLI pipeline SHALL execute the gather, deduplicate, enrich, score, and output stages sequentially for every run and SHALL emit status updates for each stage via the logger and progress renderer.

#### Scenario: Standard run updates every stage
- **WHEN** `execute_run` starts without early exits
- **THEN** the logger reports "GATHER", "DEDUP", "ENRICH", "SCORE", and "OUTPUT" stages in order
- **AND** the status renderer tracks progress for each stage until completion

### Requirement: Candidate Ingestion Order
The pipeline SHALL source candidates in the following priority: (1) resume from an enriched cache when requested and available, (2) reuse Pub2Tools exports or explicit input files, and (3) invoke the Pub2Tools CLI when no local input is available and the run is not offline.

#### Scenario: Resume from enriched cache succeeds
- **WHEN** `--resume-from-enriched` is set and the cache file exists
- **THEN** the pipeline reloads candidates from the cache and skips fetching from other sources

#### Scenario: Offline run skips Pub2Tools fetch
- **WHEN** no local input exists and `offline=True`
- **THEN** the pipeline SHALL NOT call the Pub2Tools CLI and proceeds with an empty candidate list

### Requirement: Enrichment Controls
The pipeline SHALL scrape homepages and enrich Europe PMC metadata only when the respective enrichment flags are enabled, the run is online, and the execution is not resuming from an enriched cache; otherwise, it SHALL log that the enrichment step was skipped with the reason.

#### Scenario: Online enrichment executes
- **WHEN** enrichment is enabled, `offline=False`, and no enriched cache is reused
- **THEN** the pipeline invokes homepage scraping for each candidate and Europe PMC enrichment with progress updates

#### Scenario: Offline run documents skipped enrichment
- **WHEN** `offline=True`
- **THEN** both homepage scraping and Europe PMC enrichment are skipped and the logger notes the offline reason

### Requirement: Scoring and Classification Rules
The pipeline SHALL use LLM scoring by default, fall back to heuristic scoring when the run is offline or the LLM health check fails, compute `doc_score_v2` using weighted documentation subscores, and only classify a candidate as `add` when both bio and documentation thresholds are met **and** the execution path (B2 ≥ 0.5 or A4 = 1.0) and reproducibility anchor (B3 ≥ 0.5) gates pass; otherwise the candidate SHALL be classified as `review` or `do_not_add`.

#### Scenario: LLM scoring with gating passes
- **WHEN** the LLM is healthy and documentation subscores satisfy B2 ≥ 0.5 and B3 ≥ 0.5 while scores meet add thresholds
- **THEN** the candidate is classified as `add`

#### Scenario: Gating failure downgrades decision
- **WHEN** the documentation score meets thresholds but B3 = 0
- **THEN** the candidate is classified as `review` despite high aggregate scores

#### Scenario: Offline scoring uses heuristics
- **WHEN** `offline=True`
- **THEN** heuristic scoring executes for every candidate and the logger records the heuristic mode

### Requirement: Output Artifacts
Upon finishing scoring, the pipeline SHALL write the assessment report as JSONL and CSV, produce add and review payload JSON files (unless `dry_run=True`), update the entries snapshot, and terminate with an error when payload validation fails; payloads SHALL omit nested null fields.

#### Scenario: Successful output writes artifacts
- **WHEN** the run completes without validation errors and `dry_run=False`
- **THEN** the pipeline writes `<report>.jsonl`, `<report>.csv`, `biotools_payload.json`, `biotools_review_payload.json`, and `biotools_entries.json`

#### Scenario: Validation errors raise failure
- **WHEN** a payload entry fails schema validation
- **THEN** the pipeline writes an `.invalid.json` report and exits with a non-zero status
