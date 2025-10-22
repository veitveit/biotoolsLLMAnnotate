## Why
The repository lacks OpenSpec coverage for the CLI pipeline even though the functionality already exists. Documenting the currently implemented gather→dedup→enrich→score→output workflow provides the baseline required before future changes can be proposed.

## What Changes
- Describe the end-to-end CLI pipeline stages, including resume behaviours and progress reporting.
- Capture scoring behaviour, LLM fallback rules, and documentation gating as normative requirements.
- Specify the emitted assessment and payload artifacts so downstream tooling has a referenced contract.

## Impact
- Affected specs: `cli-pipeline`
- Affected code: `src/biotoolsllmannotate/cli/run.py`, `src/biotoolsllmannotate/assess/scorer.py`
