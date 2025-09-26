from .ollama_client import OllamaClient
from biotoolsllmannotate.config import get_config_yaml


def clamp_score(score: float) -> float:
    """Clamp score to [0, 1]."""
    return max(0.0, min(1.0, score))


def _candidate_homepage(candidate: dict) -> str:
    homepage = candidate.get("homepage")
    if isinstance(homepage, str) and homepage.strip():
        return homepage.strip()
    urls = candidate.get("urls") or []
    for url in urls:
        s = str(url).strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
    return ""


class Scorer:
    def __init__(self, model=None, config=None):
        self.config = config or get_config_yaml()
        self.client = OllamaClient(config=self.config)
        self.model = model or self.config.get("pipeline", {}).get("model")

    def score_candidate(self, candidate: dict) -> dict:
        import json

        prompt = self._build_prompt(candidate)
        origin_types = self._origin_types(candidate)
        response = self.client.generate(prompt, model=self.model)
        # If response is a string, parse as JSON
        if isinstance(response, str):
            response = json.loads(response)
        output_pub_ids = response.get("publication_ids")
        if isinstance(output_pub_ids, str):
            publication_ids = [output_pub_ids]
        elif isinstance(output_pub_ids, list):
            publication_ids = [str(p).strip() for p in output_pub_ids if str(p).strip()]
        else:
            publication_ids = candidate.get("publication_ids", [])

        result = {
            "tool_name": response.get("tool_name")
            or candidate.get("title")
            or candidate.get("name", ""),
            "homepage": response.get("homepage")
            or _candidate_homepage(candidate),
            "publication_ids": publication_ids,
            "bio_score": clamp_score(response.get("bio_score", 0)),
            "documentation_score": clamp_score(
                response.get("documentation_score", 0)
            ),
            "concise_description": response.get("concise_description", ""),
            "rationale": response.get("rationale", ""),
            "model": self.model,
            "model_params": {},
            "origin_types": origin_types,
        }
        return result

    def _build_prompt(self, candidate: dict) -> str:
        template = self.config.get("scoring_prompt_template")
        if not template:
            template = """Please evaluate this bioinformatics tool candidate for inclusion in bio.tools.

Tool Information:
- Title: {title}
- Description: {description}
- Homepage: {homepage}
- Documentation: {documentation}
- Repository: {repository}
- Tags: {tags}
- Published: {published_at}
- Publication Abstract: {publication_abstract}
- Publication Full Text: {publication_full_text}

Please provide a JSON response with:
- bio_score: A score from 0.0 to 1.0 indicating whether this is a bioinformatics tool or resource.
- documentation_score: A score from 0.0 to 1.0 capturing if the available documentation makes the tool usable.
- concise_description: A refined 1-2 sentence summary of the tool (avoid copying verbatim unless already concise).
- rationale: A brief explanation referencing evidence for your scores.

Respond ONLY with the JSON object. Response format: {{"bio_score": 0.8, "documentation_score": 0.9, "concise_description": "Short rewritten summary.", "rationale": "This is a bioinformatics tool..."}}"""

        publication_ids = candidate.get("publication_ids") or []
        prompt = template.format(
            title=candidate.get("title", ""),
            description=candidate.get("description", ""),
            homepage=candidate.get("homepage", ""),
            documentation=", ".join(candidate.get("documentation", [])),
            repository=candidate.get("repository", ""),
            tags=", ".join(candidate.get("tags", [])),
            published_at=candidate.get("published_at", ""),
            publication_abstract=candidate.get("publication_abstract", ""),
            publication_full_text=candidate.get(
                "publication_full_text",
                candidate.get("publication_full_text_url", ""),
            ),
            publication_ids=", ".join(publication_ids),
        )
        return prompt

    def _origin_types(self, candidate: dict) -> list[str]:
        """Return labels describing which candidate fields populated the prompt."""

        def has_value(value) -> bool:
            if value is None:
                return False
            if isinstance(value, str):
                return bool(value.strip())
            if isinstance(value, (list, tuple, set)):
                return any(str(item).strip() for item in value)
            return True

        mapping = [
            ("title", "title"),
            ("description", "description"),
            ("homepage", "homepage"),
            ("documentation", "documentation"),
            ("repository", "repository"),
            ("tags", "tags"),
            ("published_at", "publication"),
            ("publication_abstract", "publication_abstract"),
            ("publication_full_text", "publication_full_text"),
            ("publication_full_text_url", "publication_full_text_url"),
            ("publication_ids", "publication_ids"),
        ]
        origins: list[str] = []
        for key, label in mapping:
            if has_value(candidate.get(key)):
                origins.append(label)
        return origins
