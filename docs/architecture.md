# Architecture and Data Flow

This document provides a high-level overview of how the CLI pipeline processes candidates and how the main modules collaborate. The diagrams use [Mermaid](https://mermaid.js.org/) so they render inline on GitHub and within most Markdown viewers.

## Pipeline Data Flow
```mermaid
flowchart LR
    subgraph Gather
        P2T["Pub2Tools Export\n(to_biotools.json)"]
        CLIInput["User Input\n(--input / --resume)"]
        Registry["Registry Snapshot\n(optional)"]
        Load["load_candidates"]
        P2T --> Load
        CLIInput --> Load
        Registry -.-> Load
    end

    subgraph Deduplicate
        Load --> Dedup["merge_edam_tags + dedup"]
    end

    subgraph Enrich
        Dedup --> Scrape["Homepage Scraper\n(enrich.scraper)"]
        Scrape --> EuropePMC["Europe PMC Enrichment"]
        EuropePMC --> Cache["cache/enriched_candidates.json.gz"]
    end

    subgraph Score
        Cache --> ScoreOne["ThreadPoolExecutor\nscore_one()
 -- offline? --> HeuristicScorer"]
        ScoreOne -->|LLM healthy| LLMScorer["Scorer (Ollama)"]
        ScoreOne -->|offline/LLM failure| HeuristicScorer["Heuristic scoring"]
        LLMScorer --> Reports
        HeuristicScorer --> Reports
    end

    subgraph Output
        Reports["reports/assessment.jsonl + .csv"] --> Decisions["decision rows"]
        Decisions --> PayloadAdd["exports/biotools_payload.json"]
        Decisions --> PayloadReview["exports/biotools_review_payload.json"]
        Decisions --> Entries["exports/biotools_entries.json"]
    end
```

## Run Lifecycle
```mermaid
stateDiagram-v2
  [*] --> LoadConfig
  LoadConfig: Load configuration file and defaults
  DetermineInput: Resolve candidate source (resume, input, Pub2Tools)
  Gather: Gather and normalise raw candidates
  Deduplicate: Merge EDAM tags and collapse duplicates
  Enrich: Scrape homepages and enrich publications
  Score: Run LLM or heuristic scorer
  Output: Emit payloads and reports
  CacheArtifacts: Persist resume checkpoints

  LoadConfig --> DetermineInput
  DetermineInput --> Gather
  Gather --> Deduplicate
  Deduplicate --> Enrich
  Enrich --> Score
  Score --> Output
  Output --> CacheArtifacts
  CacheArtifacts --> [*]

  Gather --> CacheArtifacts: --resume-from-pub2tools
  Enrich --> CacheArtifacts: --resume-from-enriched
  Score --> CacheArtifacts: --resume-from-scoring
```

## Module Collaboration
```mermaid
classDiagram
    direction LR
    class PromptBuilder {
      +build(candidate)
      +augment(base, errors)
      +origin_types(candidate)
    }

    class LLMRetryManager {
      +run(prompt, builder) : (payload, diagnostics)
    }

    class SchemaValidator {
      +validate(payload) : List[str]
    }

    class ScoreNormalizer {
      +bio() : ScoreBreakdown
      +documentation() : DocumentationScore
      +confidence() : float
      +publication_ids() : List[str]
      +homepage() : str
    }

    class Scorer {
      -PromptBuilder prompt_builder
      -SchemaValidator validator
      -LLMRetryManager retry_manager
      +score_candidate(candidate) : dict
    }

    class FrameCrawlLimiter {
      +can_fetch_more()
      +depth_allowed(depth)
      +record_fetch()
    }

    class ScrapeMetrics {
      +add_error(label, message, url, context)
      +to_dict()
      +to_error_list()
    }

    class scrape_homepage_metadata {
      <<function>>
    }

    PromptBuilder <-- Scorer
    SchemaValidator <-- LLMRetryManager
    LLMRetryManager <-- Scorer
    ScoreNormalizer <-- Scorer
    FrameCrawlLimiter <-- scrape_homepage_metadata
    ScrapeMetrics <-- scrape_homepage_metadata
```

## Stage Coordination Sequence
```mermaid
sequenceDiagram
  participant User
  participant CLI as CLI Runner
  participant Pipeline as Pipeline Controller
  participant Gather as Gather Stage
  participant Enrich as Enrichment Stage
  participant Score as Scoring Stage
  participant Output as Output Stage

  User->>CLI: biotoolsannotate [flags]
  CLI->>Pipeline: load_config()
  Pipeline->>Gather: resolve_candidates()
  Gather-->>Pipeline: candidates, provenance
  Pipeline->>Enrich: scrape_and_merge()
  Enrich-->>Pipeline: enriched candidates + metrics
  Pipeline->>Score: score_candidates()
  Score-->>Pipeline: assessment rows (LLM/heuristic)
  Pipeline->>Output: write_reports()
  Output-->>Pipeline: payload manifests
  Pipeline-->>CLI: run summary + telemetry
  CLI-->>User: exit code, console report
```

## Key Notes
- **Telemetry**: `LLMRetryManager` returns `RetryDiagnostics` and `ScoreNormalizer` adds weighted documentation scores so the JSONL output now records `model_params.attempts`, `model_params.schema_errors`, and `model_params.prompt_augmented` when retries occur.
- **Shared utilities**: `FrameCrawlLimiter` and `ScrapeMetrics` keep homepage scraping bounded while retaining rich error context for the pipeline status panel.
- The diagrams highlight only the core pipeline nodes. Supporting modules (configuration loading, CLI parsing, registry helpers) follow the same modular pattern and are omitted for brevity.
