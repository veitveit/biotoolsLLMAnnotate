# BioToolsLLMAnnotate

A modular CLI pipeline for annotating bio.tools entries using Pub2Tools, enrichment, LLM assessment, and strict schema validation.

## Features
- Fetch candidate tools from Pub2Tools or local files
- Enrich with homepage, documentation, repository evidence, and Europe PMC publication summaries
- Assess bioinformatics relevance and documentation quality using an Ollama LLM
- Deduplicate, score, and filter candidates
- Output strict biotoolsSchema JSON payload and per-candidate report
- Advanced CLI flags: batching, concurrency, quiet/verbose, offline mode
- Robust error handling, validation gate, and progress logging
- Built-in Pub2Tools wrapper with automatic classpath management
- Timeout protection for long-running operations
- Rich progress bars for better user experience

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
ollama pull llama3.2  # if using LLM assessment
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
  to_biotools_file: "/path/to/pub2tools_export.json"  # optional, any filename
```

**Supported Formats:**
- **Native executable:** `/path/to/pub2tools`
- **Java .jar:** `java -jar /path/to/pub2tools-1.1.1.jar`
- **Custom command:** Any command string that launches Pub2Tools

If not configured, the pipeline will look for `pub2tools` in your PATH or in `tools/pub2tools/pub2tools`.

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
python -m biotoolsllmannotate --from-date 7d --min-score 0.6 --output out/payload.json --report out/report.jsonl

# Test with sample data
python -m biotoolsllmannotate --input tests/fixtures/pub2tools/sample.json --dry-run --report out/report.jsonl

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
- `out/payload.json`: biotoolsSchema-compliant JSON for upload
- `out/report.jsonl`: Per-candidate report with bio/documentation scores, rationale, and evidence
- `out/report.csv`: Spreadsheet-friendly version of the report (`tool_name`, `homepage`, publication IDs, `bio_score`, `documentation_score`, `concise_description`, rationale, origins)
- `out/updated_entries.json`: Full biotoolsSchema payload for accepted tools, ready for upload/merge

## LLM Scoring
- Each candidate receives two scores from the configured Ollama model:
  - `bio_score`: how confidently the entry represents a bioinformatics tool or resource
  - `documentation_score`: whether available docs/support are sufficient for practical use
- `tool_name`: model-selected display name (falls back to candidate title if unchanged)
- `homepage`: model-confirmed best homepage URL
- `publication_ids`: identifiers (PMID, PMCID, DOI) derived from candidate metadata or Europe PMC
- `concise_description`: a 1–2 sentence summary the model rewrites if the source text is weak
- Both scores range from 0.0–1.0 and must exceed `--min-score` (default 0.6) for inclusion.
- To customise the instructions, edit `scoring_prompt_template` in `config.yaml`; the CLI falls back to the same text bundled in `biotoolsllmannotate.config.DEFAULT_CONFIG_YAML`.

### Europe PMC Enrichment
- When `enrichment.europe_pmc.enabled` is true (default), the pipeline pulls abstracts and (by default) truncated full text for each candidate publication with a PMID/PMCID/DOI.
- Disable `enrichment.europe_pmc.include_full_text` if you prefer to skip the full-text fetch or reduce prompt size.
- The post-processing step writes `out/updated_entries.json`, combining the enriched metadata with the latest LLM inferences.
- Toggle `enrichment.europe_pmc.include_full_text` if you want the prompt to include the open-access body of the article (truncated to `max_full_text_chars`).
- The enrichment step is skipped automatically in `--offline` mode or when no publication identifiers are present.

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
