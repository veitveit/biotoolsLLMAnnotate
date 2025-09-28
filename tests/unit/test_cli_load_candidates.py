import json
import os
import sys
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from biotoolsllmannotate.cli.run import load_candidates


def test_load_candidates_wrapped_list(tmp_path):
    data = {"count": 1, "list": [{"id": "wrapped", "title": "Wrapped Tool"}]}
    path = Path(tmp_path) / "wrapped.json"
    path.write_text(json.dumps(data))

    candidates = load_candidates(str(path))

    assert len(candidates) == 1
    assert candidates[0]["id"] == "wrapped"


def test_load_candidates_missing_file(tmp_path):
    missing_path = Path(tmp_path) / "missing.json"
    candidates = load_candidates(str(missing_path))
    assert candidates == []


def test_load_candidates_array(tmp_path):
    data = [{"id": "array", "title": "Array Tool"}]
    path = Path(tmp_path) / "array.json"
    path.write_text(json.dumps(data))

    candidates = load_candidates(str(path))

    assert len(candidates) == 1
    assert candidates[0]["id"] == "array"


def test_load_candidates_merges_edam_tags(tmp_path):
    data = {
        "count": 1,
        "list": [
            {
                "id": "tagged",
                "title": "Tagged Tool",
                "tags": ["Existing"],
                "topic": [{"term": "Topic Term"}],
                "function": [
                    {
                        "operation": [
                            {"label": "Operation Label"},
                            {"term": "Operation Label"},
                        ],
                        "input": [
                            {
                                "data": {"name": "Data Term"},
                                "format": [
                                    {"name": "Format Name"},
                                    {"term": "Topic Term"},
                                ],
                            }
                        ],
                        "output": [
                            {
                                "data": "Output Data",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = Path(tmp_path) / "tags.json"
    path.write_text(json.dumps(data))

    candidates = load_candidates(str(path))

    assert len(candidates) == 1
    tags = candidates[0]["tags"]
    assert set(tags) == {
        "Existing",
        "Topic Term",
        "Operation Label",
        "Data Term",
        "Format Name",
        "Output Data",
    }
