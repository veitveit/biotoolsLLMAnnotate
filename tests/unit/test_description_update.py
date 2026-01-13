"""Test that to_entry uses LLM-generated concise_description from scores."""

from biotoolsllmannotate.cli.run import to_entry


def test_to_entry_uses_concise_description_from_scores():
    """Verify that to_entry prefers concise_description from scores over original description."""
    candidate = {
        "name": "TestTool",
        "description": "Original pub2tools description that is verbose and long",
        "homepage": "https://example.com",
        "biotoolsID": "testtool",
        "function": [
            {
                "operation": [
                    {
                        "uri": "http://edamontology.org/operation_0001",
                        "term": "Analysis",
                    }
                ]
            }
        ],
        "topic": [{"uri": "http://edamontology.org/topic_0003", "term": "Topic"}],
    }

    scores = {
        "concise_description": "A concise LLM-generated description.",
        "bio_score": 0.8,
        "documentation_score": 0.7,
    }

    # Call to_entry with scores
    entry = to_entry(candidate, "https://example.com", scores)

    # Verify the LLM-generated description is used
    assert entry["description"] == "A concise LLM-generated description."
    assert entry["description"] != candidate["description"]

    # Verify other fields are preserved
    assert entry["name"] == "TestTool"
    assert entry["homepage"] == "https://example.com"
    assert entry["biotoolsID"] == "testtool"
    assert "function" in entry
    assert "topic" in entry


def test_to_entry_fallback_without_scores():
    """Verify that to_entry falls back to original description when scores not provided."""
    candidate = {
        "name": "TestTool",
        "description": "Original description",
        "homepage": "https://example.com",
        "biotoolsID": "testtool",
    }

    # Call to_entry without scores
    entry = to_entry(candidate, "https://example.com", None)

    # Verify original description is kept
    assert entry["description"] == "Original description"


def test_to_entry_fallback_empty_concise_description():
    """Verify fallback when scores exist but concise_description is empty."""
    candidate = {
        "name": "TestTool",
        "description": "Original description",
        "homepage": "https://example.com",
        "biotoolsID": "testtool",
    }

    scores = {
        "concise_description": "",  # Empty
        "bio_score": 0.5,
    }

    entry = to_entry(candidate, "https://example.com", scores)

    # Verify original description is kept when concise_description is empty
    assert entry["description"] == "Original description"


def test_to_entry_strips_confidence_flag():
    """Ensure internal confidence hints are removed from outgoing payloads."""

    candidate = {
        "name": "TestTool",
        "homepage": "https://example.com",
        "biotoolsID": "testtool",
        "confidence_flag": "high",
    }

    entry = to_entry(candidate, "https://example.com", None)

    assert "confidence_flag" not in entry
