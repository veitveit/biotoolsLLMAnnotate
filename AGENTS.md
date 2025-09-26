# Repository Guidelines

This guide sets expectations for contributing code, tests, and docs to this repository.

## Project Structure & Module Organization
- Use a src layout: `src/biotoolsllmannotate/` for library/CLI code (e.g., `cli.py`, `edam/`, `io/`).
- Place tests in `tests/`, mirroring package paths (e.g., `tests/edam/test_mapping.py`).
- Keep exploratory work in `notebooks/`; strip outputs before committing.
- Store small sample data in `data/sample/`; use Git LFS or external links for large files.

## Build, Test, and Development Commands
- Create env: `python -m venv .venv && source .venv/bin/activate`.
- Install (dev): `pip install -e .[dev]`.
- Run tests: `pytest -q`.
- Lint/format: `ruff check . && black .`.
- Type check: `mypy src`.
- CLI help (if present): `python -m biotoolsllmannotate --help`.

## Coding Style & Naming Conventions
- Python 3.10+; follow PEP 8. Black line length 88; Ruff for linting. Use Google/NumPy-style docstrings.
- Names: packages/modules `lower_snake`, classes `CapWords`, functions/vars `lower_snake`, constants `UPPER_SNAKE`.
- Files: tests named `test_*.py`; fixtures under `tests/fixtures/`.

## Testing Guidelines
- Use pytest. Prefer small, deterministic tests; isolate I/O and network.
- Aim for ≥90% coverage on touched code: `pytest --cov=biotoolsllmannotate --cov-report=term-missing`.
- Share fixtures via `tests/conftest.py`; mock external services and file system.

## Commit & Pull Request Guidelines
- Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `perf:`; optional scope (e.g., `feat(cli): ...`).
- PRs must include: clear description, linked issues (e.g., `Fixes #123`), tests and docs updates, and before/after examples for CLI or API changes.
- Keep PRs focused and small; avoid unrelated refactors.

## Security & Configuration
- Do not commit secrets or large datasets. Provide `.env.example`; load real values from an untracked `.env.local`.
- Pin dependencies in `pyproject.toml` or `requirements*.txt`. Run `pre-commit run -a` before pushing.

## Agent-Specific Instructions
- When modifying files, follow these conventions, keep patches minimal, and update this document if conventions change.

