import json
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional, Tuple, Union

from .ollama_client import OllamaClient, OllamaConnectionError
from biotoolsllmannotate.config import get_config_yaml
from biotoolsllmannotate.enrich import is_probable_publication_url


JSON_RESPONSE_SCHEMA = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": [
    "tool_name",
    "homepage",
    "publication_ids",
    "bio_subscores",
    "documentation_subscores",
    "concise_description",
    "rationale"
  ],
  "additionalProperties": false,
  "properties": {
    "tool_name": {"type": "string"},
    "homepage": {"type": "string"},
    "publication_ids": {
      "type": "array",
      "items": {"type": "string"}
    },
    "bio_subscores": {
      "type": "object",
      "required": ["A1", "A2", "A3", "A4", "A5"],
      "properties": {
        "A1": {"type": "number"},
        "A2": {"type": "number"},
        "A3": {"type": "number"},
        "A4": {"type": "number"},
        "A5": {"type": "number"}
      },
      "additionalProperties": {"type": "number"}
    },
    "documentation_subscores": {
      "type": "object",
      "required": ["B1", "B2", "B3", "B4", "B5"],
      "properties": {
        "B1": {"type": "number"},
        "B2": {"type": "number"},
        "B3": {"type": "number"},
        "B4": {"type": "number"},
        "B5": {"type": "number"}
      },
      "additionalProperties": {"type": "number"}
    },
    "concise_description": {"type": "string"},
    "rationale": {"type": "string"}
  }
}"""

_EXPECTED_TOP_LEVEL_TYPES = {
    "tool_name": str,
    "homepage": str,
    "publication_ids": list,
    "bio_subscores": Mapping,
    "documentation_subscores": Mapping,
    "concise_description": str,
    "rationale": str,
}

_BIO_KEYS = ("A1", "A2", "A3", "A4", "A5")
_DOC_KEYS = ("B1", "B2", "B3", "B4", "B5")


def _schema_validation_errors(response: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(response, Mapping):
        return ["response is not a JSON object"]

    for key, expected_type in _EXPECTED_TOP_LEVEL_TYPES.items():
        if key not in response:
            errors.append(f"missing field '{key}'")
            continue
        value = response[key]
        if not isinstance(value, expected_type):
            errors.append(
                f"field '{key}' must be of type {expected_type.__name__}, got {type(value).__name__}"
            )

    publication_ids = response.get("publication_ids")
    if isinstance(publication_ids, list):
        for idx, item in enumerate(publication_ids):
            if not isinstance(item, str):
                errors.append(
                    f"publication_ids[{idx}] must be a string, got {type(item).__name__}"
                )

    def _check_scores(container: Any, keys: Tuple[str, ...], label: str) -> None:
        if not isinstance(container, Mapping):
            errors.append(f"field '{label}' must be an object")
            return
        for key in keys:
            if key not in container:
                errors.append(f"missing field '{label}.{key}'")
                continue
            value = container[key]
            if not isinstance(value, (int, float)):
                errors.append(
                    f"field '{label}.{key}' must be numeric, got {type(value).__name__}"
                )
        for extra_key, extra_value in container.items():
            if extra_key in keys:
                continue
            if not isinstance(extra_value, (int, float)):
                errors.append(
                    f"field '{label}.{extra_key}' must be numeric, got {type(extra_value).__name__}"
                )

    _check_scores(response.get("bio_subscores"), _BIO_KEYS, "bio_subscores")
    _check_scores(
        response.get("documentation_subscores"), _DOC_KEYS, "documentation_subscores"
    )

    for text_field in ("tool_name", "homepage", "concise_description", "rationale"):
        value = response.get(text_field)
        if not isinstance(value, str):
            errors.append(
                f"field '{text_field}' must be a string, got {type(value).__name__}"
            )

    return errors


def _safe_fill_template(template: str, fields: Mapping[str, Any]) -> str:
    """Replace known placeholders without interpreting other braces.

    This avoids KeyErrors when custom templates contain literal braces like
    "{0, 0.5, 1}" while still supporting the `{placeholder}` fields we expose.
    """

    result = template
    for key, value in fields.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def clamp_score(score: float) -> float:
    """Clamp score to [0, 1]."""
    return max(0.0, min(1.0, score))


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _coerce_subscore_container(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return None
        # Attempt to split comma-separated strings like "1,0.5,0"
        parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
        if len(parts) >= 2:
            floats = []
            for part in parts:
                num = _coerce_float(part)
                if num is None:
                    break
                floats.append(num)
            if len(floats) == len(parts):
                return floats
        return None
    return raw


def _normalize_subscores(raw):
    container = _coerce_subscore_container(raw)
    if isinstance(container, Mapping):
        normalized: dict[str, float] = {}
        for key, value in container.items():
            num = _coerce_float(value)
            if num is not None:
                normalized[str(key)] = num
        return normalized or None
    if isinstance(container, Sequence) and not isinstance(container, (str, bytes)):
        normalized_list: list[float] = []
        for value in container:
            num = _coerce_float(value)
            if num is not None:
                normalized_list.append(num)
        return normalized_list or None
    return None


def _average_from_normalized(normalized) -> float | None:
    if normalized is None:
        return None
    if isinstance(normalized, dict):
        values = list(normalized.values())
    else:
        values = list(normalized)
    if not values:
        return None
    return sum(values) / len(values)


def _canonicalize_breakdown(breakdown, canonical_order: Sequence[str] | None):
    if breakdown is None:
        return None
    if canonical_order:
        canonical_order = list(canonical_order)
        if isinstance(breakdown, dict):
            result: dict[str, float] = {}
            for key in canonical_order:
                result[key] = float(breakdown.get(key, 0.0))
            for key, value in breakdown.items():
                if key not in result:
                    result[str(key)] = float(value)
            return result
        if isinstance(breakdown, Sequence) and not isinstance(breakdown, (str, bytes)):
            result = {}
            for idx, key in enumerate(canonical_order):
                if idx < len(breakdown):
                    result[key] = float(breakdown[idx])
                else:
                    result[key] = 0.0
            return result
    return breakdown


def _score_from_response(
    response: Mapping,
    candidate_keys: Sequence[str],
    canonical_order: Sequence[str] | None,
) -> tuple[float, Mapping | Sequence | None]:
    breakdown = None
    averaged = None
    for key in candidate_keys:
        if key not in response:
            continue
        normalized = _normalize_subscores(response.get(key))
        if normalized is None:
            continue
        canonical = _canonicalize_breakdown(normalized, canonical_order)
        breakdown = canonical
        averaged = _average_from_normalized(canonical)
        if averaged is not None:
            break
    if breakdown is None and canonical_order:
        breakdown = {key: 0.0 for key in canonical_order}
    if averaged is None:
        averaged = _average_from_normalized(breakdown) if breakdown is not None else 0.0
    if averaged is None:
        averaged = 0.0
    return clamp_score(averaged), breakdown


def _candidate_homepage(candidate: dict) -> str:
    homepage = candidate.get("homepage")
    if isinstance(homepage, str):
        stripped = homepage.strip()
        if stripped and not is_probable_publication_url(stripped):
            return stripped
    urls = candidate.get("urls") or []
    for url in urls:
        s = str(url).strip()
        if not s:
            continue
        if is_probable_publication_url(s):
            continue
        if s.startswith("http://") or s.startswith("https://"):
            return s
    return ""


class Scorer:
    def __init__(self, model=None, config=None):
        self.config = config or get_config_yaml()
        self.client = OllamaClient(config=self.config)
        self.model = model or self.config.get("ollama", {}).get("model")

    def score_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Score a candidate using LLM with proper error handling."""
        if not isinstance(candidate, dict):
            raise ValueError("Candidate must be a dictionary")

        if not candidate.get("title") and not candidate.get("name"):
            raise ValueError("Candidate must have either 'title' or 'name' field")

        base_prompt = self._build_prompt(candidate)
        origin_types = self._origin_types(candidate)

        raw_schema_retries = self.config.get("ollama", {}).get("schema_retries", 1)
        try:
            schema_retries = int(raw_schema_retries)
        except (TypeError, ValueError):
            schema_retries = 1
        schema_retries = max(0, schema_retries)

        attempts = 1 + schema_retries
        response_payload: Optional[Dict[str, Any]] = None
        last_errors: List[str] = []
        successful_attempts: Optional[int] = None

        for attempt in range(attempts):
            prompt = (
                base_prompt
                if attempt == 0
                else self._augment_prompt_with_errors(base_prompt, last_errors)
            )
            try:
                raw_response = self.client.generate(prompt, model=self.model)
            except OllamaConnectionError as e:
                raise ValueError(f"LLM scoring failed: {e}") from e
            except ValueError as e:
                last_errors = [str(e)]
                if attempt == attempts - 1:
                    raise ValueError(
                        "LLM scoring failed to produce valid JSON after retries"
                    ) from e
                continue

            if isinstance(raw_response, str):
                try:
                    parsed_response = json.loads(raw_response)
                except json.JSONDecodeError as exc:
                    last_errors = [f"JSON parse error: {exc}"]
                    if attempt == attempts - 1:
                        raise ValueError(
                            "LLM scoring produced invalid JSON after retries"
                        ) from exc
                    continue
            elif isinstance(raw_response, Mapping):
                parsed_response = dict(raw_response)
            else:
                last_errors = [
                    f"Unexpected response type: {type(raw_response).__name__}"
                ]
                if attempt == attempts - 1:
                    raise ValueError(
                        "LLM scoring returned an unexpected payload type"
                    )
                continue

            validation_errors = _schema_validation_errors(parsed_response)
            if validation_errors:
                last_errors = validation_errors
                if attempt == attempts - 1:
                    joined = "; ".join(validation_errors)
                    raise ValueError(
                        f"LLM scoring response violated schema after retries: {joined}"
                    )
                continue

            response_payload = parsed_response
            successful_attempts = attempt + 1
            break

        if response_payload is None:
            raise ValueError("LLM scoring failed: empty response payload")

        response = response_payload

        output_pub_ids = response.get("publication_ids")
        if isinstance(output_pub_ids, str):
            publication_ids = [output_pub_ids]
        elif isinstance(output_pub_ids, list):
            publication_ids = [str(p).strip() for p in output_pub_ids if str(p).strip()]
        else:
            publication_ids = candidate.get("publication_ids", [])

        bio_score, bio_breakdown = _score_from_response(
            response,
            ("bio_subscores", "bio_subcriteria", "bio_components"),
            ("A1", "A2", "A3", "A4", "A5"),
        )
        doc_score, doc_breakdown = _score_from_response(
            response,
            (
                "documentation_subscores",
                "documentation_subcriteria",
                "documentation_components",
            ),
            ("B1", "B2", "B3", "B4", "B5"),
        )

        homepage_value = ""
        for option in (response.get("homepage"), _candidate_homepage(candidate)):
            if isinstance(option, str):
                stripped = option.strip()
                if stripped and not is_probable_publication_url(stripped):
                    homepage_value = stripped
                    break

        model_params: Dict[str, Any] = {}
        if successful_attempts is not None:
            model_params["attempts"] = successful_attempts

        result = {
            "tool_name": response.get("tool_name")
            or candidate.get("title")
            or candidate.get("name", ""),
            "homepage": homepage_value,
            "publication_ids": publication_ids,
            "bio_score": bio_score,
            "documentation_score": doc_score,
            "concise_description": response.get("concise_description", ""),
            "rationale": response.get("rationale", ""),
            "model": self.model,
            "model_params": model_params,
            "origin_types": origin_types,
        }
        result["bio_subscores"] = bio_breakdown or {}
        result["documentation_subscores"] = doc_breakdown or {}
        return result

    def _build_prompt(self, candidate: dict) -> str:
        template = self.config.get("scoring_prompt_template")
        if not template:
            template = """You are evaluating whether a software resource is worth getting registered in bio.tools, the registry for software resources in the life sciences.

Available material:

Title: {title}
Description: {description}
Homepage: {homepage}
Homepage status: {homepage_status}
Homepage error: {homepage_error}
Documentation links: {documentation}
Documentation keywords found on homepage: {documentation_keywords}
Repository: {repository}
Found keywords: {tags}
Published: {published_at}
Publication abstract: {publication_abstract}
Publication full text: {publication_full_text}
Known publication identifiers: {publication_ids}

Task:
Score the resource using the rubric below. For every subcriterion assign exactly one of {{0, 0.5, 1}}. Base every decision only on the provided material. Do not invent facts or URLs. If the resource is not life-science software, set ALL bio subcriteria A1–A5 = 0 and explain why in the rationale.

Bio score rubric
A1 Biological intent stated (explicit life-science task/domain).
A2 Operations on biological data described
A3 Software with biological data I/O: 0 = none; 0.5 = only generic; 1 = concrete datatypes/formats named.
A4 Modality explicitly classifiable as one or more of: database portal, desktop application, web application, web API, web service, SPARQL endpoint, command-line tool (CLI), workbench, suite, plug-in, workflow, library, ontology. Include minimal usage context.
A5 Evidence of bio use (examples on real bio data OR peer-reviewed/benchmark citation).

Documentation score rubric (subcriteria only; no overall score here)
B1 Documentation completeness (e.g. manual, guide, readthedocs).
B2 Installation pathways (e.g. installation/setup, config, container, package).
B3 Reproducibility aids (e.g. doi, release).
B4 Maintenance signal (e.g. commits, issue tracker, news).
B5 Onboarding & support (e.g. quickstart/tutorial, contact, faq).

Selection/normalization rules:

Base every decision on the supplied material only.
Normalize publication identifiers to prefixes: DOI:..., PMID:..., PMCID:... and remove duplicates (case-insensitive).
For any subcriterion scored 0 due to missing evidence, mention "insufficient evidence: <item>" in the rationale.
Record each bio subcriterion as numbers {{0,0.5,1}} in `bio_subscores` and each documentation subcriterion as numbers {{0,0.5,1}} in `documentation_subscores`.
Do NOT compute aggregate scores; only fill the provided fields.
Do not output any value outside [0.0, 1.0].
Always emit every field in the output JSON exactly once.
Emit ONLY the fields in the schema below. Use "" for unknown strings and [] if no publication identifiers are found. Do not output booleans/strings instead of numbers.

JSON schema describing the required output:
{json_schema}

Before replying, validate your draft against this schema. If the JSON does not pass validation, fix it and revalidate until it does. Output only the validated JSON; never include commentary or surrounding text.

Output: respond ONLY with a single JSON object shaped as:
{{
"tool_name": "<derived display name>",
"homepage": "<best homepage URL>",
"publication_ids": ["DOI:...", "PMID:...", "PMCID:..."],
"bio_subscores": {{"A1": <0|0.5|1>, "A2": <0|0.5|1>, "A3": <0|0.5|1>, "A4": <0|0.5|1>, "A5": <0|0.5|1>}},
"documentation_subscores": {{"B1": <0|0.5|1>, "B2": <0|0.5|1>, "B3": <0|0.5|1>, "B4": <0|0.5|1>, "B5": <0|0.5|1>}},
"concise_description": "<1–2 sentence rewritten summary>",
"rationale": "<2–5 sentences citing specific evidence for both score groups; for each claim indicate the source as one of: homepage, documentation, repository, abstract, full_text, tags; explicitly name missing items as 'insufficient evidence: ...'>"
}}"""

        publication_ids = candidate.get("publication_ids") or []
        documentation_value = candidate.get("documentation")
        documentation_list = []
        if isinstance(documentation_value, str):
            documentation_list = [documentation_value]
        elif isinstance(documentation_value, Sequence) and not isinstance(
            documentation_value, str
        ):
            for item in documentation_value:
                if isinstance(item, dict) and item.get("url"):
                    documentation_list.append(str(item["url"]))
                elif not isinstance(item, dict):
                    documentation_list.append(str(item))

        tags_value = candidate.get("tags") or []
        tags_str = (
            ", ".join(str(tag) for tag in tags_value)
            if isinstance(tags_value, Sequence) and not isinstance(tags_value, str)
            else str(tags_value)
        )

        homepage_status = candidate.get("homepage_status")
        homepage_error = candidate.get("homepage_error")
        doc_keywords_value = candidate.get("documentation_keywords")
        if isinstance(doc_keywords_value, str):
            documentation_keywords = doc_keywords_value.strip() or "None"
        elif isinstance(doc_keywords_value, Sequence) and not isinstance(
            doc_keywords_value, str
        ):
            documentation_keywords = (
                ", ".join(str(v) for v in doc_keywords_value if str(v).strip())
                or "None"
            )
        else:
            documentation_keywords = "None"

        prompt = _safe_fill_template(
            template,
            {
                "title": candidate.get("title", ""),
                "description": candidate.get("description", ""),
                "homepage": candidate.get("homepage", ""),
                "documentation": ", ".join(documentation_list),
                "repository": candidate.get("repository", ""),
                "tags": tags_str,
                "published_at": candidate.get("published_at", ""),
                "publication_abstract": candidate.get("publication_abstract", ""),
                "publication_full_text": candidate.get(
                    "publication_full_text",
                    candidate.get("publication_full_text_url", ""),
                ),
                "publication_ids": ", ".join(publication_ids),
                "homepage_status": homepage_status or "",
                "homepage_error": homepage_error or "",
                "documentation_keywords": documentation_keywords,
                "json_schema": JSON_RESPONSE_SCHEMA,
            },
        )
        return prompt

    def _augment_prompt_with_errors(self, base_prompt: str, errors: Sequence[str]) -> str:
        bullet_list = "\n".join(f"- {error}" for error in errors)
        return (
            f"{base_prompt}\n\n"
            "The previous response did not validate against the JSON schema because:\n"
            f"{bullet_list}\n"
            "Respond again with a corrected JSON object that satisfies every rule."
        )

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
