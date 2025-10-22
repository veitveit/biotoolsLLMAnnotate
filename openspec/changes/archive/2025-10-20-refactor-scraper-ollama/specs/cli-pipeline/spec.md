## ADDED Requirements
### Requirement: Homepage Metadata Extraction
The enrichment stage SHALL fetch homepage content with configurable timeouts, byte-size guardrails, and iframe limits, reject publication-only URLs, and merge documentation, repository, and keyword metadata from both the root document and a bounded crawl of nested frames; it SHALL emit homepage status and error labels when fetching fails.

#### Scenario: Publication homepage is filtered
- **WHEN** the primary homepage candidate resolves to a publication URL and an alternative non-publication URL exists
- **THEN** the enrichment stage selects the non-publication URL and updates the candidate homepage accordingly

#### Scenario: Non-HTML content is reported
- **WHEN** the fetched homepage advertises a non-text content type or exceeds the byte limit
- **THEN** the enrichment stage marks `homepage_scraped=False`, records a descriptive `homepage_error`, and keeps the candidate available for scoring

#### Scenario: Frame crawl extends metadata
- **WHEN** nested frames yield additional documentation links or repository URLs before the frame fetch and depth limits are exhausted
- **THEN** the enrichment stage merges the new metadata into the candidate without duplicating existing documentation entries

### Requirement: LLM Scoring Output Normalisation
The scoring stage SHALL construct prompts from available candidate metadata, request JSON responses that satisfy the published schema, retry with schema error context, and normalise the payload into `bio_score`, `documentation_score`, `doc_score_v2`, publication IDs, homepage, and confidence values with bounded attempts tracking.

#### Scenario: Schema retries capture validation errors
- **WHEN** the initial LLM response is missing required fields
- **THEN** the scorer augments the prompt with validation errors, retries up to the configured limit, and raises a failure if the response never satisfies the schema

#### Scenario: Subscores are normalised and weighted
- **WHEN** the LLM returns numeric documentation subscores in any iterable or mapping form
- **THEN** the scorer normalises them into canonical B1–B5 keys, applies the weighted `doc_score_v2`, and exposes both the weighted score and raw breakdown in the result

#### Scenario: Publication IDs and homepage are sanitised
- **WHEN** publication identifiers or homepages are returned in string or list form
- **THEN** the scorer coerces them into trimmed lists, filters out publication-only homepages, and falls back to candidate URLs when the response omits a valid homepage

#### Scenario: Retry diagnostics are emitted
- **WHEN** schema retries occur or prompt augmentation is needed
- **THEN** the scorer records `model_params` telemetry containing the attempt count and per-attempt schema error details for downstream auditing
