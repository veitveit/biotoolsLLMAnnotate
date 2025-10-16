from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from biotoolsllmannotate.registry import (
    BioToolsRegistry,
    load_registry_from_pub2tools,
)


def _write_registry(tmp_path: Path, filename: str = "biotools.json") -> Path:
    """Write a minimal registry snapshot into the temp directory."""
    dump_path = tmp_path / filename
    dump_path.write_text(
        json.dumps(
            [
                {
                    "name": "Example Tool",
                    "homepage": "https://example.org/",
                    "biotoolsID": "example",
                    "synonym": ["ExampleTool", "example-tool"],
                },
                {
                    "title": "Second Tool",
                    "link": [
                        {
                            "url": "http://second.example/path/",
                            "type": ["Homepage"],
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )

    return dump_path


def test_registry_lookup_and_name_presence(tmp_path: Path) -> None:
    """Registry tracks name presence separately from homepage matches."""
    dump_path = _write_registry(tmp_path)
    registry = BioToolsRegistry.from_json(dump_path)

    assert registry.contains_name("Example Tool") is True
    assert registry.contains_name("exampletool") is True
    assert registry.contains_name("missing tool") is False
    assert registry.contains("Example Tool", "https://example.org") is True
    assert registry.contains("exampletool", "http://example.org/") is True
    assert registry.contains("Example Tool", "https://other.example") is False
    assert registry.contains("Second Tool", "https://second.example/path") is True
    assert registry.contains("Second Tool", "https://second.example/other") is False
    assert registry.contains(None, "https://example.org") is False
    assert registry.contains("Example Tool", None) is False

    registry.add_entry({"name": "NoHome Tool"})
    assert registry.contains_name("NoHome Tool") is True
    assert registry.contains("NoHome Tool", "https://nohome.example") is False


def test_load_registry_from_pub2tools_directory(tmp_path: Path) -> None:
    """Loading from pub2tools directory yields registry instance."""
    snapshot_dir = tmp_path / "pub2tools"
    snapshot_dir.mkdir()
    _write_registry(snapshot_dir, "biotools_entries.json")

    registry = load_registry_from_pub2tools(snapshot_dir)

    assert registry is not None
    assert registry.contains("Example Tool", "https://example.org")


def test_load_registry_from_pub2tools_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Missing snapshot directory logs a debug message."""
    logger = logging.getLogger("test.registry")
    with caplog.at_level("DEBUG"):
        registry = load_registry_from_pub2tools(tmp_path, logger=logger)

    assert registry is None
    assert any("No bio.tools registry snapshot" in msg for msg in caplog.messages)
