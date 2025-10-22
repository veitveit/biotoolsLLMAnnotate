# Project Context

## Purpose
CLI that streamlines the process of annotating and scoring bioinformatics tools in bio.tools using LLMs. It fetches candidate tools from Pub2Tools exports, enriches them with metadata, and evaluates their relevance and documentation quality using an Ollama model. At last it generates biotoolsSchema-compliant payloads and assessment reports.

## Tech Stack
- Python 3.10+
- Key libraries: requests, pyyaml, ollama-python
- LLM: Ollama (local model)

## Project Conventions

### Code Style
Robust implenentation following PEP 8 guidelines. Use `black` for code formatting and `flake8` for linting. Short, effective and precise code, avoid large functions and extensive implementations.

### Architecture Patterns
Modular design with clear separation of concerns. Each pipeline stage (fetching, enriching, scoring) is encapsulated in its own module/class. Use dependency injection for better testability.

### Testing Strategy
Unit tests for individual functions and integration tests for end-to-end pipeline validation. Use `pytest` as the testing framework. Aim for high code coverage, especially on critical components.

### Git Workflow
Follow Git Flow branching model. Use feature branches for new work, and open pull requests for code reviews before merging into `main`. Write clear commit messages following Conventional Commits specification. Make commits after each larger change.

## Domain Context
Bioinformatics tools often require specific metadata and contextual information to be effectively annotated and scored. Understanding the typical structure and content of tool descriptions, documentation, and associated publications is crucial for accurate assessment.

## Important Constraints
- Conservative rules for adding tools to bio.tools
- Compliance with bio.tools metadata standards
- Performance requirements for real-time scoring
- Privacy and security considerations for handling sensitive data
- Scalability to accommodate growing numbers of tools and annotations

## External Dependencies
- Pub2Tools: Source of candidate tool records (URL: https://github.com/bio-tools/pub2tools/)
- Ollama: Local LLM for scoring (URL: https://ollama.com/)
- bio.tools API: For validating and submitting annotated tools (URL: https://biotools.readthedocs.io/en/latest/api_reference.html)
- biotoolsSchema: Metadata schema for tool annotations (URL: https://biotools.readthedocs.io/en/latest/schema/biotoolsSchema.html)
- EDAM ontology: For consistent terminology in tool descriptions (URL: https://edamontology.org/)
