## 1. Baseline Coverage
- [x] 1.1 Extract representative homepage fixtures and scorer responses for regression tests
- [x] 1.2 Capture current scraper metadata footprint and scorer payload handling in unit/contract tests

## 2. Scraper Refactor
- [x] 2.1 Factor HTTP fetching, HTML sanitisation, and metadata extraction into testable helpers
- [x] 2.2 Introduce shared utilities for keyword matching, frame crawling limits, and publication URL detection
- [x] 2.3 Add structured error objects and metrics emitted back to the pipeline

## 3. Scorer Refactor
- [x] 3.1 Encapsulate prompt construction, schema validation, and retry logic into dedicated classes
- [x] 3.2 Normalise subscore parsing, weighting, and confidence handling with explicit data structures
- [x] 3.3 Emit attempts/diagnostics in a consistent telemetry payload and extend tests accordingly

## 4. Documentation & Config
- [x] 4.1 Update CLI pipeline spec deltas with new guarantees as they stabilise
- [x] 4.2 Refresh README/usage docs and sample configs if fields or toggles change
