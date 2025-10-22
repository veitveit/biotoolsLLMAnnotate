import os
import sys
import json
from pathlib import Path
import copy

import pytest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from biotoolsllmannotate.assess.scorer import Scorer, clamp_score
from biotoolsllmannotate.config import DEFAULT_CONFIG_YAML
from biotoolsllmannotate.enrich import normalize_candidate_homepage


class StubClient:
    def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
        # Return out-of-range to verify clamping in scorer
        return {
            "tool_name": "GeneAnnotator",
            "homepage": "",
            "publication_ids": [],
            "bio_subscores": {
                "A1": 2,
                "A2": 2,
                "A3": 2,
                "A4": 2,
                "A5": 2,
            },
            "documentation_subscores": {
                "B1": -1,
                "B2": -1,
                "B3": -1,
                "B4": -1,
                "B5": -1,
            },
            "concise_description": "Concise summary.",
            "rationale": "test",
            "confidence_score": 1.0,
        }


def test_score_candidate_clamps_and_returns_rationale():
    candidate = {"title": "GeneAnnotator", "description": "A test tool."}
    scorer = Scorer()
    scorer.client = StubClient()  # Inject stub client
    result = scorer.score_candidate(candidate)
    assert result["tool_name"] == "GeneAnnotator"
    assert result["homepage"] == ""
    assert result["publication_ids"] == []
    assert result["bio_score"] == 1.0
    assert result["documentation_score"] == 0.0
    assert result["bio_subscores"] == {
        "A1": 2.0,
        "A2": 2.0,
        "A3": 2.0,
        "A4": 2.0,
        "A5": 2.0,
    }
    assert result["documentation_subscores"] == {
        "B1": -1.0,
        "B2": -1.0,
        "B3": -1.0,
        "B4": -1.0,
        "B5": -1.0,
    }
    assert result["doc_score_v2"] == pytest.approx(0.0)
    assert isinstance(result.get("rationale"), str) and result["rationale"]
    assert result["concise_description"] == "Concise summary."
    assert result["origin_types"] == ["title", "description"]
    assert result["confidence_score"] == 1.0
    assert result["model_params"] == {"attempts": 1, "schema_errors": []}


class SubscoreClient:
    def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
        return {
            "tool_name": "LLM Tool",
            "homepage": "https://provided.example",
            "publication_ids": ["DOI:10.1000/example"],
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
            "confidence_score": 0.75,
        }


def test_score_candidate_averages_subscores():
    candidate = {"title": "AvgTool"}
    scorer = Scorer()
    scorer.client = SubscoreClient()
    result = scorer.score_candidate(candidate)
    assert result["tool_name"] == "LLM Tool"
    assert result["homepage"] == "https://provided.example"
    assert result["bio_score"] == pytest.approx(0.6)
    assert result["documentation_score"] == pytest.approx(0.3571428571)
    assert result["documentation_score_raw"] == pytest.approx(0.3)
    assert result["doc_score_v2"] == pytest.approx(0.3571428571)
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
    assert result["confidence_score"] == pytest.approx(0.75)
    assert result["model_params"] == {"attempts": 1, "schema_errors": []}


class RetryClient:
    def __init__(self):
        self.calls = 0
        self.prompts = []

    def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
        self.calls += 1
        self.prompts.append(prompt)
        if self.calls == 1:
            return {
                "tool_name": "",
                "homepage": "",
                "publication_ids": [],
                "bio_subscores": {"A1": 0, "A2": 0, "A3": 0, "A4": 0, "A5": 0},
                "documentation_subscores": {
                    "B1": 0,
                    "B2": 0,
                    "B3": 0,
                    "B4": 0,
                    "B5": "invalid",
                },
                "concise_description": "",
                "rationale": "",
                "confidence_score": 0.2,
            }
        return {
            "tool_name": "Retry Tool",
            "homepage": "https://retry.example",
            "publication_ids": ["PMID:12345"],
            "bio_subscores": {"A1": 1, "A2": 1, "A3": 1, "A4": 1, "A5": 1},
            "documentation_subscores": {
                "B1": 1,
                "B2": 1,
                "B3": 1,
                "B4": 1,
                "B5": 1,
            },
            "concise_description": "Valid summary.",
            "rationale": "Valid rationale.",
            "confidence_score": 0.9,
        }


def test_score_candidate_retries_on_schema_failure():
    candidate = {"title": "Retry Tool"}
    scorer = Scorer()
    retry_client = RetryClient()
    scorer.client = retry_client
    scorer.config.setdefault("ollama", {})["schema_retries"] = 1
    result = scorer.score_candidate(candidate)

    assert retry_client.calls == 2
    assert any(
        "The previous response did not validate" in prompt
        for prompt in retry_client.prompts[1:]
    )
    assert result["tool_name"] == "Retry Tool"
    assert result["homepage"] == "https://retry.example"
    params = result["model_params"]
    assert params["attempts"] == 2
    assert params.get("prompt_augmented") is True
    assert params["schema_errors"]
    assert any(
        "documentation_subscores.B5" in err for err in params["schema_errors"][0]
    )


class PublicationHomepageClient:
    def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
        return {
            "tool_name": "Publication Tool",
            "homepage": "https://www.ncbi.nlm.nih.gov/pubmed/?term=39745644",
            "publication_ids": ["PMID:39745644"],
            "bio_subscores": {"A1": 1, "A2": 1, "A3": 1, "A4": 1, "A5": 1},
            "documentation_subscores": {
                "B1": 1,
                "B2": 1,
                "B3": 1,
                "B4": 1,
                "B5": 1,
            },
            "concise_description": "Desc.",
            "rationale": "Rat.",
            "confidence_score": 0.8,
        }


def test_score_candidate_filters_publication_homepage_from_response():
    candidate = {
        "title": "Publication Tool",
        "homepage": None,
        "urls": ["https://www.ncbi.nlm.nih.gov/pubmed/?term=39745644"],
    }
    scorer = Scorer()
    scorer.client = PublicationHomepageClient()

    result = scorer.score_candidate(candidate)

    assert result["homepage"] == ""
    assert "homepage" not in result.get("origin_types", [])


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
    assert "Confidence calibration guidelines" in prompt
    assert "Do not default to 0.9" in prompt
    assert "Do NOT compute aggregate scores" in prompt
    assert "confidence_score" in prompt
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


def test_build_prompt_includes_homepage_status_from_pub2tools_metadata():
    candidate = {
        "title": "BrokenTool",
        "homepage": {"url": "https://broken.example", "status": "404"},
        "homepageError": "HTTP 404",
    }
    normalize_candidate_homepage(candidate)
    scorer = Scorer()
    prompt = scorer._build_prompt(candidate)
    assert "Homepage: https://broken.example" in prompt
    assert "Homepage status: 404" in prompt
    assert "Homepage error: HTTP 404" in prompt


TESTS_DIR = Path(__file__).resolve().parent.parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"
SCORING_DIR = FIXTURES_DIR / "scoring"


def test_score_candidate_fixture_normalisation(tmp_path: Path) -> None:
    cfg = copy.deepcopy(DEFAULT_CONFIG_YAML)
    cfg.setdefault("ollama", {})["schema_retries"] = 0
    cfg["ollama"]["model"] = "fixture-model"

    response_payload = (SCORING_DIR / "ollama_response.json").read_text()
    expected = json.loads((EXPECTED_DIR / "scorer_baseline_output.json").read_text())

    class FixtureClient:
        def __init__(self, payload: str) -> None:
            self.payload = payload
            self.calls = 0

        def generate(self, prompt, model=None, temperature=None, top_p=None, seed=None):
            self.calls += 1
            return self.payload

    scorer = Scorer(config=cfg)
    fixture_client = FixtureClient(response_payload)
    scorer.client = fixture_client
    scorer.model = "fixture-model"

    candidate = {
        "title": "Fixture Tool",
        "description": "Fixture description.",
        "homepage": "https://fixture.example/tool",
        "documentation": ["https://fixture.example/docs/guide.html"],
        "repository": "https://github.com/example/fixture-tool",
        "tags": ["omics"],
        "published_at": "2024-12-01",
        "publication_ids": ["PMID:0000"],
    }

    result = scorer.score_candidate(candidate)

    assert fixture_client.calls == 1
    assert result == expected
