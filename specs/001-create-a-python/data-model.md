# Phase 1: Data Model

## Entities

### ToolCandidate
- id: string (source identifier)
- title: string
- description: string | null
- urls: list[string] (homepage, repo, docs, paper)
- tags: list[string] (Pub2Tools mined)
- published_at: datetime | null
- source: enum("pub2tools")

### Assessment
- ls_score: float in [0,1]
- relevance_score: float in [0,1]
- rationale: string (<= 512 chars)
- flags: list[string] (e.g., "no_homepage", "conflicting_names")
- model: string (e.g., "llama3:8b")
- model_params: object (temperature, top_p, seed)

### Annotation (improved)
- name: string
- description: string
- homepage: string | null (URL)
- documentation: list[string] (URLs)
- repository: string | null (URL)
- edam_topics: list[string] (EDAM URIs)
- edam_operations: list[string] (EDAM URIs)
- edam_data: list[string] (EDAM URIs)

### Decision
- include: bool
- reasons: list[string]

### UploadPayload (biotoolsSchema)
- version: string (biotoolsSchema version)  
- entries: list[BioToolsEntry]

### BioToolsEntry (subset — strict schema enforced at write time)
- name: string (required)
- description: string (required)
- homepage: string (required when available)
- biotoolsID: string | null (omitted for new tools)
- publications: list[object] (DOIs/PMIDs)
- topics/operations/datatypes: list[string] (EDAM URIs)
- other URLs: documentation, source code, issue tracker

## Relationships
- ToolCandidate → Assessment (1:1)
- ToolCandidate + Assessment → Annotation (transformation)
- Annotation + Assessment → Decision
- Decisions[include] → UploadPayload.entries

## Validation
- All floats clamped to [0,1].
- URLs validated; unreachable URLs marked but not fatal.
- Payload validated against biotoolsSchema version [NEEDS CLARIFICATION].
