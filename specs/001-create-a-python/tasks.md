# Tasks: Pub2Tools-based bio.tools Annotation CLI

1. Load plan.md from feature directory
   → Extract: tech stack (Python 3.11, ollama, pydantic, requests + parser)
## Phase 3.1: Setup
[x] T001 Create Python project structure under `src/biotoolsllmannotate/` and `tests/`
[x] T002 Add `pyproject.toml` with deps: `typer[all]`, `httpx`, `beautifulsoup4` (or `selectolax`), `pydantic`, `pydantic-core`, `tenacity`, `orjson`; dev: `pytest`, `pytest-cov`, `pytest-httpx` or `responses`, `pytest-benchmark`, `ruff`, `black`, `mypy`
[x] T003 [P] Configure tooling: `ruff.toml`, `pyproject` black (line-length 88), `mypy.ini`
[x] T004 [P] Add `pre-commit` config; hooks for ruff/black/mypy; update `README` badges later
[x] T005 Create directories:
     - `src/biotoolsllmannotate/{cli,ingest,enrich,assess,schema,io}`
     - `tests/{unit,contract,integration,fixtures}`
[x] T005a [P] Add `scripts/install_pub2tools.sh` and wrapper `bin/pub2tools`; document usage in quickstart
   → data-model.md: Entities → model tasks
## Phase 3.2: Tests First (TDD)
[x] T006 [P] Contract test CLI help in `tests/contract/test_cli_help.py` (invokes `python -m biotoolsllmannotate --help` and `biotools-annotate --help`)
[x] T007 [P] Contract test CLI run basic in `tests/contract/test_cli_run_basic.py` (since=7d, writes `out/payload.json`, `out/report.jsonl`; verify exit code, files exist)
[x] T008 [P] Contract test thresholds in `tests/contract/test_cli_run_thresholds.py` (min-score filtering; include/exclude logic)
[x] T009 [P] Unit test schema models in `tests/unit/test_schema_models.py` (validate BioToolsEntry, clamp scores, required fields)
[x] T010 [P] Unit test Pub2Tools ingest in `tests/unit/test_ingest_pub2tools.py` (parse fixture, time filter, dedup)
[x] T010a [P] Unit test Pub2Tools client in `tests/unit/test_pub2tools_client.py` (monkeypatch CLI call; ensure `run_month_all` writes `to_biotools.json` and `load_to_biotools_json` parses it)
[x] T011 [P] Unit test scraping enrichers in `tests/unit/test_enrich_scrape.py` (extract homepage/docs from HTML fixtures)
[x] T011a [P] Unit test repository evidence in `tests/unit/test_enrich_repo.py` (parse README snippet and discover docs link from raw Git hosting when provided)
[x] T012 [P] Unit test LLM scoring wrapper in `tests/unit/test_assess_llm.py` (mock ollama, deterministic outputs)
[x] T013 Integration test end-to-end in `tests/integration/test_end_to_end.py` (fixtures → payload; mocks for network and LLM)
[x] T014 [P] Add fixtures: `tests/fixtures/pub2tools/sample.json`, `tests/fixtures/html/tool_homepage.html`, `tests/fixtures/html/docs.html`, and golden `tests/fixtures/payload_minimal.json`
- [ ] T001 Create Python project structure under `src/biotoolsllmannotate/` and `tests/`
- [ ] T008 [P] Contract test thresholds in `tests/contract/test_cli_run_thresholds.py` (min-score filtering; include/exclude logic)
- [ ] T009 [P] Unit test schema models in `tests/unit/test_schema_models.py` (validate BioToolsEntry, clamp scores, required fields)
## Phase 3.3: Core Implementation (ONLY after tests are failing)
[x] T015 Implement CLI entry `src/biotoolsllmannotate/cli/main.py` using Typer; expose console script `biotools-annotate`
[x] T016 Pipeline orchestrator `src/biotoolsllmannotate/cli/run.py` (args: --since, --min-score, --limit, --dry-run, --output, --report, --model, --concurrency)
[x] T017 Ingest: `src/biotoolsllmannotate/ingest/pub2tools_fetcher.py` (parse, filter by time, dedup)
[x] T017a Ingest: `src/biotoolsllmannotate/ingest/pub2tools_client.py` (locate CLI, `run_month_all`, `load_to_biotools_json`, `fetch_via_cli`)
[x] T018 Enrich: `src/biotoolsllmannotate/enrich/scraper.py` (requests/httpx + parser; extract homepage/docs/repo; timeouts, robots.txt respect if feasible)
[x] T018a [P] Enrich repo: `src/biotoolsllmannotate/enrich/repo.py` (best-effort fetch of README/metadata from Git hosting; derive description/docs links; size/time limits)
[x] T019 Assess: `src/biotoolsllmannotate/assess/ollama_client.py` (wrapper) and `src/biotoolsllmannotate/assess/scorer.py` (prompt, scoring, rationale, clamping)
[x] T020 Schema: `src/biotoolsllmannotate/schema/models.py` (pydantic models aligned with biotoolsSchema) and validators
[x] T021 IO: `src/biotoolsllmannotate/io/payload_writer.py` (strict schema validation + write payload.json), `src/biotoolsllmannotate/io/report_writer.py` (jsonl)
[x] T022 Dedup/reconcile `src/biotoolsllmannotate/ingest/dedup.py` (by normalized title/homepage)
[x] T023 Logging/config `src/biotoolsllmannotate/io/logging.py` and `config.py` (env: `OLLAMA_MODEL`, defaults)
[x] T023a CLI: add Pub2Tools flags `--p2t-month`, `--p2t-out`, env `PUB2TOOLS_CLI`; integrate ingestion path preference (BIOTOOLS_ANNOTATE_INPUT > p2t run > CLI fetch)
[x] T023b CLI: add `--offline/--no-web` to disable web/repo fetching; ensure report marks `needs_review` when uncertainty remains
- [ ] T010 [P] Unit test Pub2Tools ingest in `tests/unit/test_ingest_pub2tools.py` (parse fixture, time filter, dedup)
- [ ] T014 [P] Add fixtures: `tests/fixtures/pub2tools/sample.json`, `tests/fixtures/html/tool_homepage.html`, `tests/fixtures/html/docs.html`, and golden `tests/fixtures/payload_minimal.json`

## Phase 3.4: Integration
[x] T024 Hook modules into pipeline; ensure streaming/batching; progress logging
[x] T025 Add retries/backoff for HTTP and LLM (tenacity), with max attempts from config
[x] T026 Add concurrency controls (async or thread pool) bounded by `--concurrency`
[x] T027 Implement validation gate: fail with exit code 2 when payload elements violate schema; still emit report
[x] T028 CLI UX polish: helpful errors, `--help` examples, quiet/verbose modes; stderr for errors, exit codes (0/2/3)
[x] T028a [P] Makefile targets: `make pub2tools MONTH=YYYY-MM` (calls wrapper), `make annotate` (runs CLI with BIOTOOLS_ANNOTATE_INPUT)
[x] T028b Respect robots.txt, set custom User-Agent, and apply conservative timeouts/rate limits for scraping and repo fetches
## Phase 3.3: Core Implementation (ONLY after tests are failing)
- [ ] T017a Ingest: `src/biotoolsllmannotate/ingest/pub2tools_client.py` (locate CLI, `run_month_all`, `load_to_biotools_json`, `fetch_via_cli`)
- [ ] T018 Enrich: `src/biotoolsllmannotate/enrich/scraper.py` (requests/httpx + parser; extract homepage/docs/repo; timeouts, robots.txt respect if feasible)
[x] T029 [P] Unit tests for error cases (bad HTML, timeouts, invalid schema)
[x] T030 [P] Performance tests/benchmarks `tests/perf/test_batch_processing.py` (p95 < 500 ms/candidate on samples)
[x] T031 [P] Update `specs/001-create-a-python/quickstart.md` with final flags and examples
[x] T031a [P] Add Pub2Tools workflow example mirroring bio-tools-curation-tooling (month run → to_biotools.json → annotate)
[x] T031b [P] Document evidence policy: when uncertain, consult website/docs/repo; how to enable/disable and where evidence appears in the report
[x] T032 [P] Add example output files under `examples/` (sanitized)
[x] T033 Run format/lint/type/coverage: `ruff check .`, `black .`, `mypy src`, `pytest --cov=biotoolsllmannotate --cov-report=term-missing`
- [ ] T020 Schema: `src/biotoolsllmannotate/schema/models.py` (pydantic models aligned with biotoolsSchema) and validators
## Validation Checklist
[x] All contracts have corresponding tests
[x] All entities have model tasks
[x] All tests come before implementation
[x] Parallel tasks truly independent
[x] Each task specifies exact file path
[x] No task modifies same file as another [P] task
## Phase 3.4: Integration
- [ ] T024 Hook modules into pipeline; ensure streaming/batching; progress logging
- [ ] T025 Add retries/backoff for HTTP and LLM (tenacity), with max attempts from config
- [ ] T026 Add concurrency controls (async or thread pool) bounded by `--concurrency`
- [ ] T027 Implement validation gate: fail with exit code 2 when payload elements violate schema; still emit report
- [ ] T028 CLI UX polish: helpful errors, `--help` examples, quiet/verbose modes; stderr for errors, exit codes (0/2/3)
 - [ ] T028a [P] Makefile targets: `make pub2tools MONTH=YYYY-MM` (calls wrapper), `make annotate` (runs CLI with BIOTOOLS_ANNOTATE_INPUT)
 - [ ] T028b Respect robots.txt, set custom User-Agent, and apply conservative timeouts/rate limits for scraping and repo fetches

## Phase 3.5: Polish
- [ ] T029 [P] Unit tests for error cases (bad HTML, timeouts, invalid schema)
- [ ] T030 [P] Performance tests/benchmarks `tests/perf/test_batch_processing.py` (p95 < 500 ms/candidate on samples)
- [ ] T031 [P] Update `specs/001-create-a-python/quickstart.md` with final flags and examples
 - [ ] T031a [P] Add Pub2Tools workflow example mirroring bio-tools-curation-tooling (month run → to_biotools.json → annotate)
 - [ ] T031b [P] Document evidence policy: when uncertain, consult website/docs/repo; how to enable/disable and where evidence appears in the report
- [ ] T032 [P] Add example output files under `examples/` (sanitized)
- [ ] T033 Run format/lint/type/coverage: `ruff check .`, `black .`, `mypy src`, `pytest --cov=biotoolsllmannotate --cov-report=term-missing`

## Dependencies
- Setup (T001–T005) before tests and implementation
- Tests (T006–T014) before core implementation (T015–T023)
- Models (T020) before writer (T021) and CLI pipeline (T016)
- Ingest (T017) before dedup (T022) and pipeline (T016)
- Assess (T019) and Enrich (T018) before pipeline (T016)
- Integration (T024–T028) before Polish (T029–T033)

## Parallel Example
```
# Launch contract + unit tests in parallel (after setup):
Task: "Contract test CLI help in tests/contract/test_cli_help.py"
Task: "Contract test CLI run basic in tests/contract/test_cli_run_basic.py"
Task: "Unit test schema models in tests/unit/test_schema_models.py"
Task: "Unit test Pub2Tools ingest in tests/unit/test_ingest_pub2tools.py"
Task: "Unit test scraping enrichers in tests/unit/test_enrich_scrape.py"
Task: "Unit test LLM scoring wrapper in tests/unit/test_assess_llm.py"
```

## Validation Checklist
- [ ] All contracts have corresponding tests
- [ ] All entities have model tasks
- [ ] All tests come before implementation
- [ ] Parallel tasks truly independent
- [ ] Each task specifies exact file path
- [ ] No task modifies same file as another [P] task
