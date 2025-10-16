from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)
from biotoolsllmannotate.ingest import pub2tools_client


def test_fetch_from_export(tmp_path: Path) -> None:
    """Load entries from a simple export file."""
    data = [{"id": "tool1", "title": "Tool One"}, {"id": "tool2", "title": "Tool Two"}]
    export_path = tmp_path / "sample.json"
    export_path.write_text(str(data).replace("'", '"'))
    result = pub2tools_client.fetch_from_export(export_path)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["id"] == "tool1"


def test_load_to_biotools_json(tmp_path: Path) -> None:
    """Load records from to_biotools.json."""
    data = [{"id": "toolA", "title": "Tool A"}]
    out_dir = tmp_path
    tb_path = out_dir / "to_biotools.json"
    tb_path.write_text(json.dumps(data))
    result = pub2tools_client.load_to_biotools_json(out_dir)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["id"] == "toolA"


def test_load_to_biotools_json_wrapped_list(tmp_path: Path) -> None:
    """Handle CLI exports that wrap entries inside a list key."""
    data = {"count": 1, "list": [{"id": "toolB", "title": "Tool B"}]}
    out_dir = tmp_path
    tb_path = out_dir / "to_biotools.json"
    tb_path.write_text(json.dumps(data))
    result = pub2tools_client.load_to_biotools_json(out_dir)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["id"] == "toolB"


def test_find_cli_with_command_string() -> None:
    """Test that _find_cli handles command strings (not just file paths)."""
    # Test with a command string like "java -jar /path/to/jar"
    command_string = "java -jar /path/to/pub2tools.jar"
    result = pub2tools_client._find_cli(command_string)
    assert result == command_string


def test_find_cli_with_file_path() -> None:
    """Test that _find_cli handles actual file paths."""
    # Create a temporary executable file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write("#!/bin/bash\necho 'test'\n")
        f.flush()
        os.chmod(f.name, 0o755)

        try:
            result = pub2tools_client._find_cli(f.name)
            assert result == f.name
        finally:
            os.unlink(f.name)


def test_find_cli_with_nonexistent_file() -> None:
    """Return provided path even if binary does not exist."""
    nonexistent_path = "/path/to/nonexistent/file"
    result = pub2tools_client._find_cli(nonexistent_path)
    # Now returns the path even if it doesn't exist, treating it as a command string
    assert result == nonexistent_path


def test_find_cli_with_none() -> None:
    """Fall back to configuration when no CLI override present."""
    # Test with None - should check environment, config, and PATH
    with patch.dict(os.environ, {}, clear=True):
        result = pub2tools_client._find_cli(None)
        # Should return the config value since config.yaml exists
        from biotoolsllmannotate.config import get_config_yaml

        expected = get_config_yaml().get("pub2tools", {}).get("p2t_cli")
        assert result == expected


def test_find_cli_with_env_var() -> None:
    """Prefer PUB2TOOLS_CLI environment override when set."""
    test_cli = "/custom/path/to/pub2tools"
    with patch.dict(os.environ, {"PUB2TOOLS_CLI": test_cli}):
        result = pub2tools_client._find_cli(None)
        assert result == test_cli
