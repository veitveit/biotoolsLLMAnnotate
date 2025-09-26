# Feature Specification: Pub2Tools-based bio.tools Annotation CLI

**Feature Branch**: `001-create-a-python`  
**Created**: 2025-09-21  
**Status**: Draft  
**Input**: User description: "Create a python CLI that gets literature mined bio.tools annotations for newly published tools using Pub2Tools. These annotations then are revise by an LLM to check for their correctness and suitability to describe a software tool in the life sciences. The assessment should include scoring of whether the tool is related to life sciences / bioinformatics and whether it is relevant enough (has documentation, web page, ...). After that, our tool should improve the annotations and create a json for upload to bio.tools."

## Execution Flow (main)
```
1. Parse user description from Input
   → If empty: ERROR "No feature description provided"
2. Extract key concepts from description
   → Identify: actors, actions, data, constraints
3. For each unclear aspect:
   → Mark with [NEEDS CLARIFICATION: specific question]
4. Fill User Scenarios & Testing section
   → If no clear user flow: ERROR "Cannot determine user scenarios"
5. Generate Functional Requirements
   → Each requirement must be testable
   → Mark ambiguous requirements
6. Identify Key Entities (if data involved)
7. Run Review Checklist
   → If any [NEEDS CLARIFICATION]: WARN "Spec has uncertainties"
   → If implementation details found: ERROR "Remove tech details"
8. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

### Section Requirements
- **Mandatory sections**: Must be completed for every feature
- **Optional sections**: Include only when relevant to the feature
- When a section doesn't apply, remove it entirely (don't leave as "N/A")

### For AI Generation
When creating this spec from a user prompt:
1. **Mark all ambiguities**: Use [NEEDS CLARIFICATION: specific question] for any assumption you'd need to make
2. **Don't guess**: If the prompt doesn't specify something (e.g., "login system" without auth method), mark it
3. **Think like a tester**: Every vague requirement should fail the "testable and unambiguous" checklist item
4. **Common underspecified areas**:
   - User types and permissions
   - Data retention/deletion policies  
   - Performance targets and scale
   - Error handling behaviors
   - Integration requirements
   - Security/compliance needs

---

## User Scenarios & Testing (mandatory)

### Primary User Story
As a biotools curator, I want a CLI that fetches newly mined tool candidates from Pub2Tools, assesses their suitability for bio.tools using an LLM, improves the annotations, and outputs a ready-to-upload JSON so I can quickly populate bio.tools with high-quality entries.

### Acceptance Scenarios
1. Given new tool candidates exist in Pub2Tools, When I run the CLI with default options, Then it retrieves candidates, assesses each with scores (life-science relevance and overall relevance), suggests improved annotations, and writes a JSON file in bio.tools schema.
2. Given a candidate lacks sufficient evidence (no website or docs), When processed, Then the tool outputs a low relevance score with rationale and excludes it from the final JSON unless explicitly forced by a flag.
3. Given an invalid Pub2Tools source or network failure, When I run the CLI, Then it reports a clear error and exits with a non-zero code without producing partial/invalid JSON.
4. Given multiple candidates, When I set a minimum score threshold, Then only candidates meeting or exceeding the threshold are included in the output JSON.
5. Given Pub2Tools is installed or a wrapper is configured, When I run the CLI with a month flag (e.g., `--p2t-month 2025-08`), Then Pub2Tools runs end-to-end to an output directory and the tool consumes `to_biotools.json` for assessment and improvement.
6. Given annotations are incomplete or LLM assessment is uncertain, When processing a candidate, Then the system consults primary sources (tool website, documentation, and if necessary repository README/code metadata) to corroborate details; if uncertainty remains, it marks the entry `needs_review` with reasons in the report and excludes it by default.

### Edge Cases
- Pub2Tools returns duplicates or conflicting annotations → deduplicate and reconcile with rationale.
- Tools with non-life-science domains but shared names → score low LS relevance with explicit justification.
- Missing metadata fields (e.g., no homepage) → mark, request human review, exclude by default.
- Extremely large candidate list → process in batches; produce incremental checkpoints.

## Requirements (mandatory)

### Functional Requirements
- FR-001: The system MUST ingest Pub2Tools output in two ways: (a) read an existing `to_biotools.json` export, or (b) invoke the Pub2Tools CLI (Java) via a configured wrapper to generate it for a given period.
- FR-002: The system MUST assess each candidate via an LLM for (a) life-science/bioinformatics relevance and (b) overall suitability (evidence of documentation, website, etc.).
- FR-003: The system MUST produce numeric scores in [0, 1] for LS relevance and overall relevance, plus a short textual rationale per candidate.
- FR-004: The system MUST improve/complete candidate annotations (name, description, homepage, documentation links, EDAM annotations if present) producing a JSON payload in bio.tools schema for upload.
- FR-005: The system MUST allow setting a minimum score threshold to include candidates in the output.
- FR-006: The system MUST emit a machine-readable report (per-candidate assessments, rationales, final decision included/excluded) alongside the JSON.
- FR-007: The system MUST provide a dry-run mode that performs assessment but does not write final JSON, only the report.
- FR-008: The system MUST provide clear CLI help and example usage and return non-zero exit codes on failure.
- FR-009: The system MUST avoid modifying existing bio.tools records; it only prepares new-entry payloads.
- FR-010: The system MUST log decisions and assumptions for curation transparency.
- FR-011: The system MUST handle duplicate or conflicting candidates by merging evidence and choosing the best annotation with justification.
- FR-012: The system MUST support pagination/batching to handle large candidate sets.
- FR-013: The system MUST expose CLI flags and envs for Pub2Tools integration: `--p2t-month YYYY-MM`, `--p2t-out <dir>`, and `PUB2TOOLS_CLI` to locate the CLI/wrapper. If `BIOTOOLS_ANNOTATE_INPUT` points to a JSON file, prefer it over running Pub2Tools.
- FR-014: The system MUST accept `to_biotools.json` (biotoolsSchema) as canonical source, map fields (name, description, homepage, docs, EDAM), and strictly validate final output against the biotoolsSchema.
- FR-015: Default thresholds: LS relevance ≥ 0.6 and overall relevance ≥ 0.6, overridable by `--min-score`.
- FR-016: The system MUST consult original sources when in doubt: fetch and parse the tool homepage, documentation, and (when available) repository README/metadata to verify name, description, and links; record consulted sources and extracted evidence in the report.
- FR-017: Provide an offline mode (`--offline` or `--no-web`) to disable external fetching; in this mode, uncertain entries are marked `needs_review` and excluded by default.

*Clarifications resolved / remaining*
- FR-016: The output MUST conform to the current biotoolsSchema as used in Pub2Tools `to_biotools.json` (validate via pydantic models). If schema versioning is required, document the chosen version in the report.
- FR-017: LLM provider is local `ollama` with a lightweight instruct model; no external network required by default.
- FR-018: Default cadence is monthly via Pub2Tools `--month` (e.g., 2025-08); ad-hoc windows remain supported via `--since` filter.
- FR-019: EDAM annotations from Pub2Tools are used as initial suggestions; LLM-assisted improvement is best-effort and MUST not invent non-existent terms.
- FR-020: Interaction with the bio.tools API (validation/upload) is out-of-scope for this feature; this tool only prepares JSON.

### Key Entities (include if feature involves data)
- P2TEntry: one entry from Pub2Tools `to_biotools.json` (already in biotoolsSchema keys).
- ToolCandidate: normalized subset from P2TEntry (name, description, urls, EDAM, pubs).
- Assessment: LLM output including LS score, relevance score, rationale, uncertainties.
- Annotation: curated/improved fields (name, description, homepage, docs, EDAM tags).
- Decision: include/exclude with threshold and reasons.
- UploadPayload: final JSON structure per bio.tools schema, one per included tool.
- Report: summary over all candidates (counts, reasons, threshold used, timing).
- Evidence: list of consulted source URLs per candidate with timestamps and brief notes, used for auditability.

---

## Review & Acceptance Checklist

### Content Quality
- [ ] No implementation details (languages, frameworks, APIs)
- [ ] Focused on user value and business needs
- [ ] Written for non-technical stakeholders
- [ ] All mandatory sections completed

### Requirement Completeness
- [ ] No [NEEDS CLARIFICATION] markers remain
- [ ] Requirements are testable and unambiguous  
- [ ] Success criteria are measurable
- [ ] Scope is clearly bounded
- [ ] Dependencies and assumptions identified

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [ ] Review checklist passed

---
