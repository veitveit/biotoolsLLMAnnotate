# BioToolsLLMAnnotate

A modular CLI pipeline for annotating bio.tools entries using Pub2Tools, enrichment, LLM assessment, and strict schema validation.

## Features
- Fetch candidate tools from Pub2Tools or local files
- Enrich with homepage, documentation, repository evidence, and Europe PMC publication summaries
- Assess bioinformatics relevance and documentation quality using an Ollama LLM
- Deduplicate, score, and filter candidates
- Output strict biotoolsSchema JSON payload and per-candidate report
- Advanced CLI flags: batching, concurrency, quiet/verbose, offline mode, default config scaffolding
- Robust error handling, validation gate, and progress logging with a live Rich scoreboard
- Built-in Pub2Tools wrapper with automatic classpath management
- Timeout protection for long-running operations
- Rich progress bars for better user experience

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
ollama pull llama3.2  # if using LLM assessment
# Optional: scaffold config.yaml with project defaults
python -m biotoolsllmannotate --write-default-config
```

### Pub2Tools Integration

The pipeline includes a working Pub2Tools wrapper script at `bin/pub2tools` that handles classpath dependencies automatically. The wrapper:

- Includes all required JAR dependencies in the classpath
- Provides memory options for Java (-Xms2048M -Xmx4096M)
- Supports all Pub2Tools commands including `-all` for full pipeline execution
- Has built-in timeout protection (10 minutes) to prevent hanging

**Usage:**
```bash
# Test the wrapper
./bin/pub2tools --help

# Run full pipeline for a date range
./bin/pub2tools -all /tmp/output --from 2023-01-01 --to 2023-01-01 --edam tools/pub2tools/edammap-src/doc/EDAM_1.25.owl --idf tools/pub2tools/edammap-src/doc/biotools.stemmed.idf --idf-stemmed tools/pub2tools/edammap-src/doc/biotools.stemmed.idf
```

### Pub2Tools CLI Setup
To fetch candidates, you need the Pub2Tools CLI. You can configure it in two ways:

**Option 1: Environment Variable**
```bash
export PUB2TOOLS_CLI="/path/to/pub2tools"
```

**Option 2: Configuration File**
```yaml
pub2tools:
  p2t_cli: "/path/to/pub2tools"

pipeline:
  resume_from_pub2tools: true  # optional, reuse cached to_biotools.json exports
  resume_from_scoring: true    # optional, reuse cached assessment results for new thresholds
```

**Supported Formats:**
- **Native executable:** `/path/to/pub2tools`
- **Java .jar:** `java -jar /path/to/pub2tools-1.1.1.jar`
- **Custom command:** Any command string that launches Pub2Tools

If not configured, the pipeline will look for `pub2tools` in your PATH or in `tools/pub2tools/pub2tools`. When `pipeline.resume_from_pub2tools` (or `--resume-from-pub2tools`) is enabled, the CLI will automatically reuse the most recent `to_biotools.json` saved under `out/<period>/pub2tools/` instead of invoking Pub2Tools again.

### Troubleshooting Pub2Tools Setup

**Using the Included Wrapper Script**: The recommended approach is to use the included wrapper script at `bin/pub2tools`, which handles all classpath dependencies automatically:

```bash
# Test the wrapper
./bin/pub2tools --help

# The wrapper automatically includes:
# - All JAR dependencies from tools/pub2tools/pub2tools-src/target/lib/
# - The pub2tools-core JAR for SelectPub class
# - Memory options (-Xms2048M -Xmx4096M)
```

**Manual Configuration**: If you need to use a different Pub2Tools CLI:

**Option 1: Environment Variable**
```bash
export PUB2TOOLS_CLI="/path/to/pub2tools"
```

**Option 2: Configuration File**
```yaml
pub2tools:
  p2t_cli: "/path/to/pub2tools"
```

**Java JAR Dependencies**: If using a Java JAR manually and encountering `NoClassDefFoundError`:
- Ensure all required JAR dependencies are in the classpath
- The wrapper script handles this automatically

**Testing Configuration**: You can test if your Pub2Tools CLI is working:
```bash
# Test with environment variable
PUB2TOOLS_CLI="./bin/pub2tools" python -m biotoolsllmannotate --offline --dry-run
```

### EuropePMC-Only Mode for Faster Fetching

The pipeline defaults to EuropePMC-only mode for faster fetching, which restricts searches to EuropePMC sources (MEDLINE and PMC) and skips journal-specific queries. This mode is significantly faster than the full mode, which includes additional queries for various terms and journals.

To enable EuropePMC-only mode, set the following in your configuration file:

```yaml
pub2tools:
  p2t_cli: "./bin/pub2tools"
  custom_restriction: "SRC:MED OR SRC:PMC"
  disable_tool_restriction: true
  timeout: 6000
  retry_limit: 0
  fetcher_threads: 4
```

Or use the environment variable:

```bash
export PUB2TOOLS_CUSTOM_RESTRICTION="SRC:MED OR SRC:PMC"
export PUB2TOOLS_DISABLE_TOOL_RESTRICTION=true
export PUB2TOOLS_TIMEOUT=6000
export PUB2TOOLS_RETRY_LIMIT=0
export PUB2TOOLS_FETCHER_THREADS=4
```

This mode is recommended for initial testing and when speed is prioritized over comprehensive coverage.

# Test with config file
echo "pub2tools:
  p2t_cli: './bin/pub2tools'" > config.yaml
python -m biotoolsllmannotate --offline --dry-run
```

## Example Usage
```bash
# Fetch recent candidates and assess them
python -m biotoolsllmannotate --from-date 7d --min-score 0.6

# Test with sample data
python -m biotoolsllmannotate --input tests/fixtures/pub2tools/sample.json --dry-run

# Reuse an existing Pub2Tools export (no rename needed)
python -m biotoolsllmannotate --input /path/to/pub2tools_export.json --dry-run

# Offline mode (no web fetching)
python -m biotoolsllmannotate --offline --quiet

# Use custom date range
python -m biotoolsllmannotate --from-date 2023-01-01 --to-date 2023-12-31 --min-score 0.6

# Test Pub2Tools wrapper directly
./bin/pub2tools --help
./bin/pub2tools -select-pub --day 2023-01-01 --edam tools/pub2tools/edammap-src/doc/EDAM_1.25.owl --idf tools/pub2tools/edammap-src/doc/biotools.stemmed.idf --idf-stemmed tools/pub2tools/edammap-src/doc/biotools.stemmed.idf --output /tmp/test
```

## Output Files
- `out/<time-period>/exports/biotools_payload.json`: biotoolsSchema-compliant JSON bundle for upload
- `out/<time-period>/exports/biotools_entries.json`: Full biotoolsSchema payload for accepted tools, ready for upload/merge
- `out/<time-period>/reports/assessment.jsonl`: Per-candidate report with bio/documentation scores, rationale, and evidence; reused when `--resume-from-scoring` is enabled so thresholds can be adjusted without rerunning LLM scoring
- `out/<time-period>/reports/assessment.csv`: Spreadsheet-friendly version of the report (`tool_name`, `homepage`, publication IDs, `bio_score`, `documentation_score`, `concise_description`, rationale, origins)
- `out/<time-period>/cache/enriched_candidates.json.gz`: Cache of enriched candidates automatically written and reused when `--resume-from-enriched` is set
- `out/<time-period>/logs/ollama.log`: Append-only trace of every LLM scoring exchange (created on first LLM call)
- `out/<time-period>/<original-config>.yaml`: Copy of the configuration used for the run (or `config.generated.yaml` when loaded from defaults)
- `out/pub2tools/run_<timestamp>/`: Raw artifacts fetched from Pub2Tools when the CLI wrapper runs

## LLM Scoring
- Each candidate receives two scores from the configured Ollama model:
  - `bio_score`: how confidently the entry represents a bioinformatics tool or resource
  - `documentation_score`: whether available docs/support are sufficient for practical use
- `tool_name`: model-selected display name (falls back to candidate title if unchanged)
- `homepage`: model-confirmed best homepage URL
- `publication_ids`: identifiers (PMID, PMCID, DOI) derived from candidate metadata or Europe PMC
- `concise_description`: a 1–2 sentence summary the model rewrites if the source text is weak
- Both scores range from 0.0–1.0 and must exceed `--min-score` (default 0.6) for inclusion.
- When online, the pipeline scrapes each homepage (respecting timeouts) to capture extra documentation and repository links; these, along with the HTTP status, are included in the prompt.
- To customise the instructions, edit `scoring_prompt_template` in `config.yaml`; the CLI falls back to the same text bundled in `biotoolsllmannotate.config.DEFAULT_CONFIG_YAML`.

### Europe PMC Enrichment

### Enrichment Cache
- Use `--enriched-cache <path>` (or set `pipeline.enriched_cache`) to write a compressed `.json.gz` snapshot of candidates after Europe PMC enrichment.
- Reuse that snapshot later with `--resume-from-enriched` (or set `pipeline.resume_from_enriched: true`) to skip Pub2Tools fetching and enrichment when iterating on scoring or prompt settings.
- Example: `python -m biotoolsllmannotate --enriched-cache out/cache/enriched_candidates.json.gz --resume-from-enriched --dry-run`
- When `enrichment.europe_pmc.enabled` is true (default), the pipeline pulls abstracts and (by default) truncated full text for each candidate publication with a PMID/PMCID/DOI.
- Disable `enrichment.europe_pmc.include_full_text` if you prefer to skip the full-text fetch or reduce prompt size.
- The post-processing step writes `out/exports/biotools_entries.json`, combining the enriched metadata with the latest LLM inferences.
- Toggle `enrichment.europe_pmc.include_full_text` if you want the prompt to include the open-access body of the article (truncated to `max_full_text_chars`).
- The enrichment step is skipped automatically in `--offline` mode or when no publication identifiers are present.

### Scoring Resume
- Use `--resume-from-scoring` (or set `pipeline.resume_from_scoring: true`) to reuse the cached `assessment.jsonl` from the time-period directory without invoking the LLM again.
- The pipeline reloads the enriched candidates cache and reapplies the current thresholds to every cached decision, regenerating `biotools_payload.json` and `biotools_entries.json` with the updated include flags.
- Pair this flag with `--resume-from-enriched` (or an existing cache) to ensure enriched candidate metadata is available; otherwise the pipeline will fall back to rerunning scoring.

## Logging & Health Checks
- Step logs now carry consistent action tags (`GATHER`, `DEDUP`, `ENRICH`, `SCRAPE`, `SCORE`, `OUTPUT`, `SUMMARY`) so you can skim runs quickly.
- Before scoring, the CLI pings the configured Ollama endpoint; if the health probe fails, the run switches to heuristic scoring and highlights the failure in the summary line (including a `llm_health_fail` counter).
- Warning messages suggest retrying with `--offline` or fixing the Ollama service whenever the fallback is triggered.

## Evidence Policy
- When uncertain, the pipeline consults website, documentation, and repository metadata
- Use `--offline` to disable web/repo fetching
- Evidence and rationale appear in the report

## Development & Testing
- Lint: `ruff check .`
- Format: `black .`
- Type check: `mypy src`
- Test: `pytest -q`
- Coverage: `pytest --cov=biotoolsllmannotate --cov-report=term-missing`

## License
MIT
