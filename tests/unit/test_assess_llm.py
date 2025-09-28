import pytest

from biotoolsllmannotate.assess.scorer import Scorer, clamp_score


class StubClient:
    def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
        # Return out-of-range to verify clamping in scorer
        return {
            "concise_description": "Concise summary.",
            "rationale": "test",
        }


def test_score_candidate_clamps_and_returns_rationale():
    candidate = {"title": "GeneAnnotator", "description": "A test tool."}
    scorer = Scorer()
    scorer.client = StubClient()  # Inject stub client
    result = scorer.score_candidate(candidate)
    assert result["tool_name"] == "GeneAnnotator"
    assert result["homepage"] == ""
    assert result["publication_ids"] == []
    assert 0.0 <= result["bio_score"] <= 1.0
    assert 0.0 <= result["documentation_score"] <= 1.0
    assert result["bio_subscores"] == {
        "A1": 0.0,
        "A2": 0.0,
        "A3": 0.0,
        "A4": 0.0,
        "A5": 0.0,
    }
    assert result["documentation_subscores"] == {
        "B1": 0.0,
        "B2": 0.0,
        "B3": 0.0,
        "B4": 0.0,
        "B5": 0.0,
    }
    assert isinstance(result.get("rationale"), str) and result["rationale"]
    assert result["concise_description"] == "Concise summary."
    assert result["origin_types"] == ["title", "description"]


class SubscoreClient:
    def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
        return {
            "tool_name": "LLM Tool",
            "homepage": "https://provided.example",
            "bio_subscores": {
                "A1": 1,
                "A2": 0.5,
                "A3": 1,
                "A4": 0.5,
                "A5": 0,
            },
            "documentation_subscores": {
                "B1": 1,
                "B2": 0.5,
                "B3": 0,
                "B4": 0,
                "B5": 0,
            },
            "concise_description": "Provided summary.",
            "rationale": "Provided rationale.",
        }


def test_score_candidate_averages_subscores():
    candidate = {"title": "AvgTool"}
    scorer = Scorer()
    scorer.client = SubscoreClient()
    result = scorer.score_candidate(candidate)
    assert result["tool_name"] == "LLM Tool"
    assert result["homepage"] == "https://provided.example"
    assert result["bio_score"] == pytest.approx(0.6)
    assert result["documentation_score"] == pytest.approx(0.3)
    assert result["bio_subscores"] == {
        "A1": 1.0,
        "A2": 0.5,
        "A3": 1.0,
        "A4": 0.5,
        "A5": 0.0,
    }
    assert result["documentation_subscores"] == {
        "B1": 1.0,
        "B2": 0.5,
        "B3": 0.0,
        "B4": 0.0,
        "B5": 0.0,
    }


def test_clamp_score():
    assert clamp_score(-1) == 0.0
    assert clamp_score(0.5) == 0.5
    assert clamp_score(2) == 1.0


def test_build_prompt_fields():
    scorer = Scorer()
    candidate = {
        "title": "TestTool",
        "description": "A tool for testing.",
        "homepage": "https://example.org",
        "documentation": ["https://example.org/docs"],
        "documentation_keywords": ["tutorial", "quickstart"],
        "repository": "https://github.com/org/testtool",
        "tags": ["genomics", "annotation"],
        "published_at": "2025-09-21",
        "publication_abstract": "This is an abstract.",
        "publication_full_text": "This is full text.",
        "publication_ids": ["PMID:12345"],
    }
    prompt = scorer._build_prompt(candidate)
    assert "TestTool" in prompt
    assert "A tool for testing." in prompt
    assert "https://example.org" in prompt
    assert "https://example.org/docs" in prompt
    assert "https://github.com/org/testtool" in prompt
    assert "genomics" in prompt
    assert "annotation" in prompt
    assert "2025-09-21" in prompt
    assert "Documentation keywords found" in prompt
    assert "tutorial, quickstart" in prompt
    assert "This is an abstract." in prompt
    assert "This is full text." in prompt
    assert "tool_name" in prompt
    assert "publication_ids" in prompt
    assert "concise_description" in prompt
    assert "rationale" in prompt
    assert "`bio_subscores`" in prompt
    assert "`documentation_subscores`" in prompt
    assert "Do NOT compute aggregate scores" in prompt
    assert "Do not output any value outside [0.0, 1.0]" in prompt
    assert "Always emit every field in the output JSON" in prompt
    assert "Output: respond ONLY with a single JSON object" in prompt
    assert scorer._origin_types(candidate) == [
        "title",
        "description",
        "homepage",
        "documentation",
        "repository",
        "tags",
        "publication",
        "publication_abstract",
        "publication_full_text",
        "publication_ids",
    ]
