#!/usr/bin/env python3
"""Summarise Ollama scoring responses and highlight malformed payloads.

This helper avoids fragile shell heredocs by living in the repo. It parses the
append-only ``out/logs/ollama.log`` file that the CLI generates and reports:

* Total scoring attempts that produced a response block.
* How many responses failed JSON parsing (e.g., truncated or extra text).
* How many parsed but violated the expected assessment schema.
* Samples of the first few failures for quick inspection.
* Optional correlation with heuristic fallbacks recorded in assessment reports.

Usage
-----

    python scripts/analyze_ollama_log.py [--log PATH] [--assessment PATH]

Both paths default to the standard output locations.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence


@dataclass(frozen=True)
class ResponseBlock:
    """A parsed response block extracted from the Ollama log."""

    raw_text: str
    problem: str | None
    payload: dict | None
    tool_name: str | None


def iter_response_chunks(log_path: Path) -> Iterable[str]:
    """Yield the raw JSON snippets logged after ``---- RESPONSE`` markers."""

    text = log_path.read_text(encoding="utf-8")
    marker = "==== BEGIN OLLAMA REQUEST"
    for chunk in text.split(marker):
        if "---- RESPONSE" not in chunk:
            continue
        try:
            response_part = chunk.split("---- RESPONSE", 1)[1]
        except IndexError:
            continue
        response_text = response_part.split("==== END OLLAMA REQUEST", 1)[0]
        stripped = response_text.strip()
        if stripped:
            yield stripped


EXPECTED_TOP_LEVEL = {
    "tool_name": str,
    "homepage": str,
    "publication_ids": list,
    "bio_subscores": dict,
    "documentation_subscores": dict,
    "concise_description": str,
    "rationale": str,
}
EXPECTED_BIO_KEYS = ["A1", "A2", "A3", "A4", "A5"]
EXPECTED_DOC_KEYS = ["B1", "B2", "B3", "B4", "B5"]


def validate_payload(payload: dict) -> Sequence[str]:
    """Return a tuple of validation errors for the response payload."""

    errors: List[str] = []

    for key, expected_type in EXPECTED_TOP_LEVEL.items():
        if key not in payload:
            errors.append(f"missing field: {key}")
            continue
        if not isinstance(payload[key], expected_type):
            actual = type(payload[key]).__name__
            errors.append(f"{key} has unexpected type {actual}")

    bios = payload.get("bio_subscores")
    if isinstance(bios, dict):
        for subkey in EXPECTED_BIO_KEYS:
            if subkey not in bios:
                errors.append(f"bio_subscores.{subkey} missing")
            elif not isinstance(bios[subkey], (int, float)):
                actual = type(bios[subkey]).__name__
                errors.append(f"bio_subscores.{subkey} has type {actual}")
    else:
        errors.append("bio_subscores not a dict")

    docs = payload.get("documentation_subscores")
    if isinstance(docs, dict):
        for subkey in EXPECTED_DOC_KEYS:
            if subkey not in docs:
                errors.append(f"documentation_subscores.{subkey} missing")
            elif not isinstance(docs[subkey], (int, float)):
                actual = type(docs[subkey]).__name__
                errors.append(f"documentation_subscores.{subkey} has type {actual}")
    else:
        errors.append("documentation_subscores not a dict")

    return errors


def analyse_log(log_path: Path, sample_limit: int) -> tuple[list[ResponseBlock], list[str]]:
    """Parse the log and classify responses."""

    responses: list[ResponseBlock] = []
    parse_fail_samples: list[str] = []
    tool_name_pattern = re.compile(r"\"tool_name\"\s*:\s*\"([^\"]*)\"")

    for chunk in iter_response_chunks(log_path):
        try:
            payload = json.loads(chunk)
        except json.JSONDecodeError as err:
            if len(parse_fail_samples) < sample_limit:
                parse_fail_samples.append(chunk)
            maybe_tool = None
            match = tool_name_pattern.search(chunk)
            if match:
                maybe_tool = match.group(1).strip() or None
            responses.append(
                ResponseBlock(
                    raw_text=chunk,
                    problem=f"json-error: {err}",
                    payload=None,
                    tool_name=maybe_tool,
                )
            )
            continue

        validation_errors = validate_payload(payload)
        problem = ", ".join(validation_errors) if validation_errors else None
        tool_name = (payload.get("tool_name") or "").strip() or None
        responses.append(
            ResponseBlock(
                raw_text=chunk,
                problem=problem,
                payload=payload,
                tool_name=tool_name,
            )
        )

    return responses, parse_fail_samples


def load_heuristic_titles(assessment_path: Path) -> set[str]:
    titles: set[str] = set()
    with assessment_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            scores = data.get("scores") or {}
            if scores.get("model") == "heuristic":
                title = (data.get("title") or "").strip()
                if title:
                    titles.add(title)
    return titles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("out/logs/ollama.log"),
        help="Path to the Ollama request/response log",
    )
    parser.add_argument(
        "--assessment",
        type=Path,
        default=None,
        help="Optional assessment JSONL to cross-check heuristic fallbacks",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=5,
        help="How many examples to show for each failure type",
    )
    args = parser.parse_args()

    if not args.log.exists():
        raise SystemExit(f"Log file not found: {args.log}")

    responses, parse_fail_samples = analyse_log(args.log, args.samples)
    total = len(responses)
    parse_failures = sum(1 for r in responses if r.payload is None)
    schema_failures = sum(1 for r in responses if r.payload is not None and r.problem)
    successes = total - parse_failures - schema_failures

    print(f"Log path: {args.log}")
    print(f"Total response blocks: {total}")
    print(f"  JSON parse failures: {parse_failures}")
    print(f"  Schema validation failures: {schema_failures}")
    print(f"  Valid payloads: {successes}")

    if parse_fail_samples:
        print("\nSample malformed JSON responses:")
        for snippet in parse_fail_samples[: args.samples]:
            preview = " ".join(snippet.splitlines())
            print(f"- {preview[:200]}")

    schema_samples = [r for r in responses if r.payload and r.problem][: args.samples]
    if schema_samples:
        print("\nSample schema issues:")
        for resp in schema_samples:
            tool = resp.tool_name or "<unknown>"
            print(f"- {tool}: {resp.problem}")

    if args.assessment:
        if not args.assessment.exists():
            raise SystemExit(f"Assessment file not found: {args.assessment}")
        heuristic_titles = load_heuristic_titles(args.assessment)
        failing_tools = {
            resp.tool_name
            for resp in responses
            if (resp.payload is None or resp.problem) and resp.tool_name
        }
        overlap = heuristic_titles & failing_tools
        missing = heuristic_titles - failing_tools
        print("\nHeuristic fallback cross-check:")
        print(f"  Titles with malformed responses: {len(overlap)}")
        if overlap:
            print("    e.g.", ", ".join(sorted(list(overlap))[: min(5, len(overlap))]))
        print(f"  Heuristic titles without logged failure: {len(missing)}")
        if missing:
            print("    e.g.", ", ".join(sorted(list(missing))[: min(5, len(missing))]))


if __name__ == "__main__":
    main()
