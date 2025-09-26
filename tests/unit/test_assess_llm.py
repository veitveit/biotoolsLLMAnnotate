def test_score_candidate_clamps_and_returns_rationale():
    from biotoolsllmannotate.assess.scorer import Scorer

    class StubClient:
        def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
            # Return out-of-range to verify clamping in scorer
            return {
                "bio_score": 1.2,
                "documentation_score": -0.5,
                "concise_description": "Concise summary.",
                "rationale": "test",
            }

    candidate = {"title": "GeneAnnotator", "description": "A test tool."}
    scorer = Scorer()
    scorer.client = StubClient()  # Inject stub client
    result = scorer.score_candidate(candidate)
    assert result["tool_name"] == "GeneAnnotator"
    assert result["homepage"] == ""
    assert result["publication_ids"] == []
    assert 0.0 <= result["bio_score"] <= 1.0
    assert 0.0 <= result["documentation_score"] <= 1.0
    assert isinstance(result.get("rationale"), str) and result["rationale"]
    assert result["concise_description"] == "Concise summary."
    assert result["origin_types"] == ["title", "description"]

    def test_clamp_score():
        from biotoolsllmannotate.assess.scorer import clamp_score

        assert clamp_score(-1) == 0.0
        assert clamp_score(0.5) == 0.5
        assert clamp_score(2) == 1.0

    def test_build_prompt_fields():
        from biotoolsllmannotate.assess.scorer import Scorer

        scorer = Scorer()
        candidate = {
            "title": "TestTool",
            "description": "A tool for testing.",
            "homepage": "https://example.org",
            "documentation": ["https://example.org/docs"],
            "repository": "https://github.com/org/testtool",
            "tags": ["genomics", "annotation"],
            "published_at": "2025-09-21",
            "publication_abstract": "This is an abstract.",
            "publication_full_text": "This is full text.",
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
        assert "This is an abstract." in prompt
        assert "This is full text." in prompt
        assert "tool_name" in prompt
        assert "publication_ids" in prompt
        assert "bio_score" in prompt
        assert "documentation_score" in prompt
        assert "concise_description" in prompt
        assert "rationale" in prompt
        assert "Respond ONLY with the JSON object." in prompt
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
