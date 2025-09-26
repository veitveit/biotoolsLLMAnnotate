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

#### `pub2tools.from_date` / `pub2tools.to_date`
- **Type**: String (ISO-8601) or null
- **Default**: `null`
- **Description**: Date range for fetching candidates (alternative to `p2t_month`)
- **CLI equivalent**: `--from-date`, `--to-date`
- **Example**: `"2024-09-01T00:00:00Z"`

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

#### `pipeline.since`
- **Type**: String (time specification)
- **Default**: `"2024-01-01"`
- **Description**: Start time for candidate selection
- **CLI equivalent**: `--since`
- **Formats**:
  - ISO-8601: `"2024-09-01T00:00:00Z"`
  - Relative: `"7d"`, `"30d"`, `"12h"`, `"2w"`, `"45m"`, `"30s"`
  - Units: `d`=days, `w`=weeks, `h`=hours, `m`=minutes, `s`=seconds

#### `pipeline.to_date`
- **Type**: String (ISO-8601) or null
- **Default**: `null` (uses current time)
- **Description**: End time for candidate selection
- **CLI equivalent**: `--to-date`
- **Example**: `"2024-09-30T23:59:59Z"`

#### `pipeline.min_score`
- **Type**: Float (0.0-1.0)
- **Default**: `0.6`
- **Description**: Minimum score threshold for inclusion
- **CLI equivalent**: `--min-score`
- **Note**: Both `bio_score` and `documentation_score` must meet this threshold

#### `pipeline.limit`
- **Type**: Integer or null
- **Default**: `null` (unlimited)
- **Description**: Maximum number of candidates to process
- **CLI equivalent**: `--limit`
- **Example**: `100`

#### `pipeline.dry_run`
- **Type**: Boolean
- **Default**: `true`
- **Description**: Run assessment only, don't write payload
- **CLI equivalent**: `--dry-run`

#### `pipeline.offline`
- **Type**: Boolean
- **Default**: `false`
- **Description**: Disable web/repository fetching
- **CLI equivalent**: `--offline`

#### `pipeline.output`
- **Type**: String (path)
- **Default**: `"out/payload.json"`
- **Description**: Output path for bio.tools payload JSON
- **CLI equivalent**: `--output`
- **Example**: `"results/payload.json"`

#### `pipeline.report`
- **Type**: String (path)
- **Default**: `"out/report.jsonl"`
- **Description**: Output path for per-candidate JSONL report
- **CLI equivalent**: `--report`
- **Example**: `"results/report.jsonl"`

#### `pipeline.updated_entries`
- **Type**: String (path)
- **Default**: `"out/updated_entries.json"`
- **Description**: Output path for the full biotoolsSchema payload containing accepted, enriched tool entries.
- **CLI equivalent**: `--updated-entries`
- **Example**: `"results/updated_entries.json"`

#### `pipeline.payload_version`
- **Type**: String
- **Default**: `"0.8.1"`
- **Description**: Version string stored alongside the updated entries payload; defaults to the package version when omitted.

#### `pipeline.input_path`
- **Type**: String (path) or null
- **Default**: `null`
- **Description**: Preferred input file (overrides Pub2Tools fetch)
- **CLI equivalent**: `--input`
- **Example**: `"data/candidates.json"`

#### `pipeline.model`
- **Type**: String
- **Default**: `"llama3.2"`
- **Description**: Ollama model name for LLM assessment
- **CLI equivalent**: `--model`
- **Example**: `"llama3.1:8b"`

#### `pipeline.concurrency`
- **Type**: Integer
- **Default**: `8`
- **Description**: Maximum concurrent jobs for fetching/scraping
- **CLI equivalent**: `--concurrency`
- **Example**: `16`

### Ollama Configuration

#### `ollama.host`
- **Type**: String (URL)
- **Default**: `"http://localhost:11434"`
- **Description**: Ollama server URL
- **Example**: `"http://localhost:11434"`

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
- **Variables**: `{title}`, `{description}`, `{homepage}`, `{documentation}`, `{repository}`, `{tags}`, `{published_at}`, `{publication_abstract}`, `{publication_full_text}`
- **Expected response keys**: `bio_score`, `documentation_score`, `concise_description`, `rationale`

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
  min_score: 0.6
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
  min_score: 0.8
  limit: 100
  model: "llama3.1:8b"
  concurrency: 8

enrichment:
  europe_pmc:
    enabled: true
    include_full_text: false

logging:
  level: "DEBUG"
  file: "logs/debug.log"
```

### Minimal Configuration
```yaml
pipeline:
  since: "2024-01-01"
  min_score: 0.6
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
biotools-annotate run --verbose --since 1d
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
| `--since 7d` | `pipeline.since: "7d"` |
| `--min-score 0.8` | `pipeline.min_score: 0.8` |
| `--model llama3.1` | `pipeline.model: "llama3.1"` |
| `--concurrency 16` | `pipeline.concurrency: 16` |
| `--offline` | `pipeline.offline: true` |
| `--p2t-cli /path/to/pub2tools` | `pub2tools.p2t_cli: "/path/to/pub2tools"` |
| `--p2t-cli "java -jar /path/to/jar"` | `pub2tools.p2t_cli: "java -jar /path/to/jar"` |

## Best Practices

1. **Start simple**: Use default config and override specific parameters
2. **Use relative time**: Prefer `"7d"` over specific dates for `since`
3. **Set reasonable limits**: Use `limit` for testing with large datasets
4. **Enable logging**: Set `logging.file` for production use
5. **Test configuration**: Use `--dry-run` to validate settings
6. **Version control**: Keep `config.yaml` in version control for reproducibility
