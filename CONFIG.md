# Configuration Guide

This guide provides comprehensive documentation for all configuration parameters in biotoolsLLMAnnotate.

## Overview

biotoolsLLMAnnotate can be configured through:
1. **Command-line arguments** (highest priority)
2. **Configuration file** (`config.yaml`)
3. **Environment variables**
4. **Default values** (lowest priority)

## Configuration File

The main configuration file is `config.yaml`. You can generate a complete example using:

```bash
biotools-annotate --write-default-config
```

## Parameter Reference

### Pub2Tools Configuration

#### `pub2tools.edam_owl`
- **Type**: String (URL)
- **Default**: `http://edamontology.org/EDAM.owl`
- **Description**: URL to the EDAM ontology OWL file used for semantic annotation
- **CLI equivalent**: `--edam-owl`

#### `pub2tools.idf`
- **Type**: String (URL)
- **Default**: `https://github.com/edamontology/edammap/raw/master/doc/biotools.idf`
- **Description**: URL to the IDF (Inverse Document Frequency) file for Pub2Tools scoring
- **CLI equivalent**: `--idf`

#### `pub2tools.idf_stemmed`
- **Type**: String (URL)
- **Default**: `https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf`
- **Description**: URL to the stemmed IDF file for Pub2Tools scoring
- **CLI equivalent**: `--idf-stemmed`

#### `pub2tools.p2t_month`
- **Type**: String (YYYY-MM) or null
- **Default**: `null`
- **Description**: Specific month to fetch from Pub2Tools using the `-all` command
- **CLI equivalent**: `--p2t-month`
- **Example**: `"2024-09"`

#### `pipeline.from_date` / `pipeline.to_date`
- **Type**: String (relative window like `7d` or ISO-8601) or null
- **Default**: `"7d"` / `null`
- **Description**: Date range for fetching candidates (alternative to `p2t_month`), applied across the entire pipeline.
- **CLI equivalent**: `--from-date`, `--to-date`
- **Example**: `"2024-09-01"` or `"30d"`

#### `pub2tools.selenium_firefox`
- **Type**: Boolean or null
- **Default**: `null`
- **Description**: Enable Selenium Firefox for web scraping
- **CLI equivalent**: `--firefox-path` (when provided)

#### `pub2tools.firefox_path`
- **Type**: String (path) or null
- **Default**: `null`
- **Description**: Path to Firefox binary for Selenium web scraping
- **CLI equivalent**: `--firefox-path`
- **Example**: `"/usr/bin/firefox"`

#### `pub2tools.p2t_cli`
- **Type**: String (path or command) or null
- **Default**: `null`
- **Description**: Path to Pub2Tools CLI executable or command string (overrides auto-detection)
- **CLI equivalent**: `--p2t-cli`
- **Examples**:
  - **File path**: `"/usr/local/bin/pub2tools"`
  - **Java .jar**: `"java -jar /path/to/pub2tools-1.1.1.jar"`
  - **Custom command**: `"java -Xmx4g -jar /opt/pub2tools.jar"`
- **Note**: If not set, the tool will auto-detect Pub2Tools CLI using environment variables and common installation paths

#### `pub2tools.output_dir`
- **Type**: String (path)
- **Default**: `"out/pub2tools"`
- **Description**: Directory for Pub2Tools output files
- **Example**: `"data/pub2tools"`

### Pipeline Configuration

> **Note:** All pipeline artifacts are written to a time-period folder (`out/<time-period>/…`) using fixed filenames. After each run the active configuration file (or a generated snapshot) is copied into that folder for record keeping.

#### `pipeline.resume_from_enriched`
- **Type**: Boolean
- **Default**: `false`
- **Description**: When `true`, the pipeline skips ingestion/enrichment and looks for the default cache file (`out/<time-period>/cache/enriched_candidates.json.gz`). No additional path configuration is required.
- **CLI equivalent**: `--resume-from-enriched`

#### `pipeline.payload_version`
- **Type**: String
- **Default**: `"__VERSION__"`
- **Description**: Version string stored alongside the updated entries payload; the placeholder resolves to the installed package version.

#### `pipeline.input_path`
- **Type**: String (path) or null
- **Default**: `null`
- **Description**: Preferred input file (overrides Pub2Tools fetch)
- **CLI equivalent**: `--input`
- **Example**: `"data/candidates.json"`

#### `pipeline.resume_from_pub2tools`
- **Type**: Boolean
- **Default**: `false`
- **Description**: When `true`, the pipeline skips the Pub2Tools CLI invocation and reuses the most recent `to_biotools.json` export found in the time-period or global `pub2tools/` cache folders. No manual path configuration is required.
- **CLI equivalent**: `--resume-from-pub2tools`

#### `pipeline.resume_from_scoring`
- **Type**: Boolean
- **Default**: `false`
- **Description**: When `true`, the pipeline reuses the cached `reports/assessment.jsonl` for the time-period folder, reapplies the current score thresholds, and regenerates payload outputs without invoking the LLM scorer again. Requires the enriched candidates cache to be present (automatically handled when `pipeline.resume_from_enriched` is also `true`).
- **CLI equivalent**: `--resume-from-scoring`

#### `pipeline.min_bio_score`
- **Type**: Float (0.0–1.0)
- **Default**: `0.6`
- **Description**: Minimum biological relevance score required for a candidate to be included in the payload. Scores come from either heuristic scoring or the LLM rubric (`A1`–`A5`).
- **CLI equivalent**: `--min-bio-score`

#### `pipeline.min_documentation_score`
- **Type**: Float (0.0–1.0)
- **Default**: `0.6`
- **Description**: Minimum documentation quality score required for inclusion, derived from rubric items `B1`–`B5`. Candidates that fail to meet this threshold are reported but excluded from the payload.
- **CLI equivalent**: `--min-doc-score`
- **Compatibility**: The legacy `pipeline.min_score` and `--min-score` options, when present, set both thresholds to the same value.

### Ollama Configuration

#### `ollama.host`
- **Type**: String (URL)
- **Default**: `"http://localhost:11434"`
- **Description**: Ollama server URL
- **Example**: `"http://localhost:11434"`

#### `ollama.model`
- **Type**: String
- **Default**: `"llama3.2"`
- **Description**: Default Ollama model name used for LLM assessment when the CLI flag is omitted.
- **CLI equivalent**: `--model`

#### `ollama.max_retries`
- **Type**: Integer
- **Default**: `3`
- **Description**: Number of retry attempts for Ollama HTTP calls after the initial request. Setting `0` disables automatic retries.
- **Example**: `5`

#### `ollama.retry_backoff_seconds`
- **Type**: Float (seconds)
- **Default**: `2.0`
- **Description**: Fixed delay between Ollama retry attempts (applied to both HTTP session retries and LLM generation retries).
- **Example**: `0.5`

#### `ollama.concurrency`
- **Type**: Integer
- **Default**: `8`
- **Description**: Maximum number of concurrent scoring workers (shared by both heuristic and LLM scoring).
- **CLI equivalent**: `--concurrency`
- **Example**: `16`

### Logging Configuration

#### `logging.level`
- **Type**: String
- **Default**: `"INFO"`
- **Description**: Logging level
- **Options**: `"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`
- **CLI equivalent**: `--verbose` (DEBUG), `--quiet` (ERROR)

#### `logging.file`
- **Type**: String (path) or null
- **Default**: `null` (console only)
- **Description**: Log file path
- **Example**: `"logs/biotools-annotate.log"`

### Europe PMC Enrichment

#### `enrichment.europe_pmc.enabled`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Toggle Europe PMC enrichment for publication metadata.
- **Effect**: When disabled, abstracts and full text are not retrieved.

#### `enrichment.europe_pmc.include_full_text`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Fetch open-access full text (truncated) when a PMCID is available.
- **Note**: Even when full text cannot be retrieved, the first available full-text URL is attached as `publication_full_text_url`.

### Homepage Scraping Enrichment

#### `enrichment.homepage.enabled`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Toggle HTML scraping of each candidate homepage to discover documentation and repository links.
- **Effect**: Disabled automatically when `--offline` or `--resume-from-enriched` is used.

#### `enrichment.homepage.timeout`
- **Type**: Integer/Float (seconds)
- **Default**: `8`
- **Description**: Network timeout applied to homepage requests.
- **Example**: `5`

#### `enrichment.homepage.user_agent`
- **Type**: String
- **Default**: `"biotoolsllmannotate/__VERSION__ (+https://github.com/ELIXIR-Belgium/biotoolsLLMAnnotate)"`
- **Description**: Custom User-Agent header for homepage scraping requests. The placeholder is replaced with the package version during configuration load.

#### `enrichment.europe_pmc.max_publications`
- **Type**: Integer
- **Default**: `1`
- **Description**: Maximum number of publication records to enrich per candidate (to limit API calls).

#### `enrichment.europe_pmc.max_full_text_chars`
- **Type**: Integer
- **Default**: `4000`
- **Description**: Maximum number of characters retained from the Europe PMC full-text XML output.

#### `enrichment.europe_pmc.timeout`
- **Type**: Integer
- **Default**: `15`
- **Description**: Timeout (seconds) for Europe PMC HTTP requests.

### Scoring Prompt Template

#### `scoring_prompt_template`
- **Type**: String (multi-line)
- **Description**: Custom prompt template for LLM scoring
- **Note**: Advanced users can customize the scoring instructions
- **Variables**: `{title}`, `{description}`, `{homepage}`, `{homepage_status}`, `{homepage_error}`, `{documentation}`, `{documentation_keywords}`, `{repository}`, `{tags}`, `{published_at}`, `{publication_abstract}`, `{publication_full_text}`, `{publication_ids}`
- **Expected response keys**: `bio_subscores`, `documentation_subscores`, `tool_name`, `homepage`, `publication_ids`, `concise_description`, `rationale`
- **LLM contract**: Return `bio_subscores` and `documentation_subscores` as JSON objects keyed by rubric IDs (A1–A5, B1–B5) with exactly one of {0, 0.5, 1} values. The pipeline computes the average from these subscores and clamps to `[0.0, 1.0]` before persisting the final scores. Normalize publication identifiers to DOI:..., PMID:..., PMCID:... format.

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `PUB2TOOLS_CLI` | Pub2Tools CLI command or path | `java -jar /path/to/pub2tools.jar` |
| `BIOTOOLS_CONFIG` | Custom config file path | `/etc/biotools-annotate/config.yaml` |
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |

**Note**: Configuration file parameters (like `pub2tools.p2t_cli`) take precedence over environment variables.

## Configuration Precedence

1. **Command-line arguments** (highest priority)
2. **Environment variables**
3. **Configuration file** (`config.yaml`)
4. **Default values** (lowest priority)

## Examples

### Basic Configuration
```yaml
pipeline:
  since: "7d"
  min_bio_score: 0.6
  min_documentation_score: 0.6
  concurrency: 16

logging:
  level: "INFO"
```

### Advanced Configuration
```yaml
pub2tools:
  p2t_month: "2024-09"
  p2t_cli: "java -jar /opt/pub2tools/pub2tools-cli-1.1.2.jar"
  firefox_path: "/usr/bin/firefox"

pipeline:
  since: "30d"
  min_bio_score: 0.8
  min_documentation_score: 0.75
  limit: 100
  model: "llama3.1:8b"
  concurrency: 8

enrichment:
  europe_pmc:
    enabled: true
    include_full_text: true

logging:
  level: "DEBUG"
  file: "logs/debug.log"
```

### Minimal Configuration
```yaml
pipeline:
  since: "2024-01-01"
  min_bio_score: 0.6
  min_documentation_score: 0.6
```

## Troubleshooting

### Common Issues

1. **Pub2Tools not found**: Set `PUB2TOOLS_CLI` environment variable or `pub2tools.p2t_cli` in config file
2. **Firefox not found**: Install Firefox or set `firefox_path` in config
3. **Ollama not accessible**: Check `ollama.host` configuration
4. **Permission errors**: Ensure write permissions for output directories

### Debug Mode

Enable debug logging to troubleshoot issues:

```bash
biotools-annotate run --verbose --from-date 1d
```

Or in config:
```yaml
logging:
  level: "DEBUG"
```

## Migration from CLI Args

When migrating from command-line arguments to config file:

| CLI Argument | Config Path |
|-------------|-------------|
| `--model llama3.1` | `ollama.model: "llama3.1"` |
| `--concurrency 16` | `ollama.concurrency: 16` |
| `--p2t-cli /path/to/pub2tools` | `pub2tools.p2t_cli: "/path/to/pub2tools"` |
| `--p2t-cli "java -jar /path/to/jar"` | `pub2tools.p2t_cli: "java -jar /path/to/jar"` |
| `--min-bio-score 0.7` | `pipeline.min_bio_score: 0.7` |
| `--min-doc-score 0.65` | `pipeline.min_documentation_score: 0.65` |

## Best Practices

1. **Start simple**: Use default config and override specific parameters
2. **Use relative time**: Prefer `"7d"` over specific dates for `pipeline.from_date`
3. **Set reasonable limits**: Use `limit` for testing with large datasets
4. **Enable logging**: Set `logging.file` for production use
5. **Test configuration**: Use `--dry-run` to validate settings
6. **Version control**: Keep `config.yaml` in version control for reproducibility
