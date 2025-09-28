# Implementation Plan: Pub2Tools-based bio.tools Annotation CLI

**Branch**: `001-create-a-python` | **Date**: 2025-09-21 | **Spec**: /home/veit/devel/Bioinformatics/ELIXIR_EDAM/biotoolsLLMAnnotate/specs/001-create-a-python/spec.md
**Input**: Feature specification from `/specs/001-create-a-python/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → If not found: ERROR "No feature spec at {path}"
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → Detect Project Type from context (web=frontend+backend, mobile=app+api)
   → Set Structure Decision based on project type
3. Fill the Constitution Check section based on the content of the constitution document.
4. Evaluate Constitution Check section below
   → If violations exist: Document in Complexity Tracking
   → If no justification possible: ERROR "Simplify approach first"
   → Update Progress Tracking: Initial Constitution Check
5. Execute Phase 0 → research.md
   → If NEEDS CLARIFICATION remain: ERROR "Resolve unknowns"
6. Execute Phase 1 → contracts, data-model.md, quickstart.md
7. Re-evaluate Constitution Check section
   → If new violations: Refactor design, return to Phase 1
   → Update Progress Tracking: Post-Design Constitution Check
8. Plan Phase 2 → Describe task generation approach (DO NOT create tasks.md)
9. STOP - Ready for /tasks command
```

## Summary
Build a Python CLI that:
- Fetches newly mined tool candidates from Pub2Tools for a given time span (e.g., last week),
- Assesses correctness/suitability via a lightweight LLM (through `ollama`),
- Scrapes tool web pages for missing evidence (homepage, docs),
- Improves annotations and outputs strict `biotoolsSchema`-compatible JSON for upload.

## Technical Context
**Language/Version**: Python 3.11 (PEP 561 typing)  
**Primary Dependencies**: Pub2Tools data source; requests/httpx; BeautifulSoup/Selectolax; pydantic for schema; ollama client  
**Storage**: local filesystem outputs (`out/*.json`, reports)  
**Testing**: pytest + pytest-cov + responses/pytest-httpx; golden files for examples  
**Target Platform**: Linux/macOS CLI  
**Project Type**: single  
**Performance Goals**: Process ≥ 100 candidates/min on typical inputs; p95 CLI step < 500 ms per candidate  
**Constraints**: Offline-friendly LLM via `ollama`; strict biotoolsSchema validation before write  
**Scale/Scope**: Batches of 10–1,000 candidates per run

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Code Quality & Simplicity: black/ruff/mypy clean; small, readable modules. PASS (planned).
- Testing Discipline: tests first where feasible; ≥90% coverage on changed areas; deterministic with mocks. PASS (planned).
- UX Consistency: stable flags (`--from-date`, `--min-score`, `--dry-run`, `--output`), `--help` with examples, proper exit codes. PASS (planned).
- Performance & Efficiency: budgets above; streaming/batching; no O(n²) over candidates. PASS (planned).
- Reproducibility & Traceability: pin deps; record inputs, model, and versions in report. PASS (planned).

## Project Structure

### Documentation (this feature)
```
specs/001-create-a-python/
├── plan.md              # This file (/plan output)
├── research.md          # Phase 0 output (/plan)
├── data-model.md        # Phase 1 output (/plan)
├── quickstart.md        # Phase 1 output (/plan)
└── contracts/
    └── cli.md           # CLI contract (Phase 1)
```

### Source Code (repository root)
```
src/
├── biotoolsllmannotate/
│   ├── cli/
│   │   └── main.py
│   ├── ingest/          # Pub2Tools fetching, dedup
│   ├── enrich/          # scraping + normalization
│   ├── assess/          # LLM scoring via ollama
│   ├── schema/          # biotoolsSchema models/validators
│   └── io/              # read/write, reports

tests/
├── unit/
├── contract/
└── integration/
```

**Structure Decision**: Option 1 (single project)

## Phase 0: Outline & Research
1. Unknowns and decisions:
   - Pub2Tools source: [NEEDS CLARIFICATION] exact endpoint/export and time filter (e.g., `--from-date 7d`).
   - LLM details: use local `ollama` model (e.g., `llama3:8b`) with deterministic settings.
   - biotoolsSchema version: [NEEDS CLARIFICATION] target schema and required fields.
   - Evidence rules: default thresholds for LS and relevance scores.
2. External references to study:
   - Pub2Tools repo and bio-tools-curation-tooling scripts (naming, filters).
3. Output: research.md summarizing selections and open questions.

## Phase 1: Design & Contracts
1. Entities and data flow → data-model.md
2. CLI contract → contracts/cli.md (args, outputs, exit codes, examples)
3. Quickstart for local run: set up `ollama`, install deps, example invocation
4. Post-design Constitution Check: PASS (no violations introduced)

## Phase 2: Task Planning Approach
- TDD ordering: tests for CLI contract, schema validation, and assess scoring first.
- Parallelization: independent modules (`ingest`, `assess`, `enrich`, `schema`, `io`).
- Performance validation: add benchmark step on sample inputs.

## Phase 3+: Future Implementation
Beyond /plan scope; generated by /tasks.

## Complexity Tracking
| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Progress Tracking
**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [ ] Phase 2: Task planning complete (/plan command - describe approach only)
- [ ] Phase 3: Tasks generated (/tasks command)

