## Why
The homepage scraper and Ollama scorer have accreted large, monolithic helpers that duplicate parsing logic, hide implicit side effects, and make it difficult to evolve metadata heuristics or scoring outputs without regressions. Refactoring them with clearer seams will let us de-duplicate shared utilities, harden validation, and add fixture-based tests before we change behaviour.

## What Changes
- Split scraper fetching, HTML sanitising, and metadata extraction into smaller units with shared utilities and guardrail enforcement
- Normalise Ollama scoring output handling, including schema retries, publication parsing, and documentation weighting, behind explicit helpers
- Introduce targeted unit and contract tests that freeze current scraper metadata fields and scorer outputs
- Surface structured errors and metrics so the pipeline can report scraper and scorer failures consistently across retries

## Impact
- Affected specs: `cli-pipeline`
- Affected code: `src/biotoolsllmannotate/enrich/scraper.py`, `src/biotoolsllmannotate/assess/scorer.py`, related tests and fixtures
