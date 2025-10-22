import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from .ollama_client import OllamaClient, OllamaConnectionError
from biotoolsllmannotate.config import DEFAULT_CONFIG_YAML, get_config_yaml
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
        "confidence_score",
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
        "confidence_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1
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
    "confidence_score": (int, float),
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
            if isinstance(expected_type, tuple):
                expected_name = ", ".join(t.__name__ for t in expected_type)
            else:
                expected_name = expected_type.__name__
            errors.append(
                f"field '{key}' must be of type {expected_name}, got {type(value).__name__}"
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

    confidence_value = response.get("confidence_score")
    if isinstance(confidence_value, (int, float)):
        if confidence_value < 0 or confidence_value > 1:
            errors.append("field 'confidence_score' must be between 0 and 1")

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


def _documentation_score_v2(breakdown, fallback: float | None) -> float:
    weights = {"B1": 2.0, "B2": 1.0, "B3": 1.0, "B4": 1.0, "B5": 2.0}
    denominator = sum(weights.values())

    if isinstance(breakdown, Mapping):
        numerator = 0.0
        have_any = False
        for key, weight in weights.items():
            raw = breakdown.get(key)
            if raw is not None:
                have_any = True
            value = _coerce_float(raw)
            if value is None:
                value = 0.0
            numerator += clamp_score(value) * weight
        if have_any:
            return clamp_score(numerator / denominator)

    if isinstance(breakdown, Sequence) and not isinstance(breakdown, (str, bytes)):
        items = list(breakdown)
        numerator = 0.0
        have_any = False
        for idx, key in enumerate(weights):
            raw = items[idx] if idx < len(items) else None
            if raw is not None:
                have_any = True
            value = _coerce_float(raw)
            if value is None:
                value = 0.0
            numerator += clamp_score(value) * list(weights.values())[idx]
        if have_any:
            return clamp_score(numerator / denominator)

    fallback_value = fallback if fallback is not None else 0.0
    return clamp_score(fallback_value)


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


@dataclass
class RetryDiagnostics:
    attempts: int
    schema_errors: List[List[str]] = field(default_factory=list)
    prompt_augmented: bool = False

    def to_model_params(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "attempts": self.attempts,
            "schema_errors": self.schema_errors,
        }
        if self.prompt_augmented:
            data["prompt_augmented"] = True
        return data


class PromptBuilder:
    def __init__(self, config: Mapping[str, Any]):
        self._config = config

    def build(self, candidate: Mapping[str, Any]) -> str:
        template = self._config.get("scoring_prompt_template")
        if not template:
            template = DEFAULT_CONFIG_YAML["scoring_prompt_template"]

        publication_ids = candidate.get("publication_ids") or []
        documentation_value = candidate.get("documentation")
        documentation_list: List[str] = []
        if isinstance(documentation_value, str):
            documentation_list = [documentation_value]
        elif isinstance(documentation_value, Sequence) and not isinstance(
            documentation_value, str
        ):
            for item in documentation_value:
                if isinstance(item, Mapping) and item.get("url"):
                    documentation_list.append(str(item["url"]))
                elif not isinstance(item, Mapping):
                    documentation_list.append(str(item))

        tags_value = candidate.get("tags") or []
        if isinstance(tags_value, Sequence) and not isinstance(tags_value, str):
            tags_str = ", ".join(str(tag) for tag in tags_value)
        else:
            tags_str = str(tags_value) if tags_value else ""

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

        return _safe_fill_template(
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

    @staticmethod
    def augment(base_prompt: str, errors: Sequence[str]) -> str:
        bullet_list = "\n".join(f"- {error}" for error in errors)
        return (
            f"{base_prompt}\n\n"
            "The previous response did not validate against the JSON schema because:\n"
            f"{bullet_list}\n"
            "Respond again with a corrected JSON object that satisfies every rule."
        )

    @staticmethod
    def origin_types(candidate: Mapping[str, Any]) -> List[str]:
        def has_value(value: Any) -> bool:
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
        origins: List[str] = []
        for key, label in mapping:
            if has_value(candidate.get(key)):
                origins.append(label)
        return origins


class SchemaValidator:
    def validate(self, payload: Any) -> List[str]:
        return _schema_validation_errors(payload)


class LLMRetryManager:
    def __init__(
        self,
        client: OllamaClient,
        model: Optional[str],
        validator: SchemaValidator,
        schema_retries: int,
    ) -> None:
        self._client = client
        self._model = model
        self._validator = validator
        self._max_attempts = max(1, 1 + schema_retries)

    def run(
        self, base_prompt: str, prompt_builder: PromptBuilder
    ) -> Tuple[Dict[str, Any], RetryDiagnostics]:
        errors_history: List[List[str]] = []
        last_errors: List[str] = []

        for attempt_index in range(self._max_attempts):
            prompt = (
                base_prompt
                if attempt_index == 0
                else prompt_builder.augment(base_prompt, last_errors)
            )
            try:
                raw_response = self._client.generate(prompt, model=self._model)
            except OllamaConnectionError as exc:
                raise ValueError(f"LLM scoring failed: {exc}") from exc
            except ValueError as exc:
                last_errors = [str(exc)]
                errors_history.append(last_errors.copy())
                if attempt_index == self._max_attempts - 1:
                    raise ValueError(
                        "LLM scoring failed to produce valid JSON after retries"
                    ) from exc
                continue

            parsed_response, parse_error, parse_exc = self._coerce_to_mapping(
                raw_response
            )
            if parse_error:
                last_errors = [parse_error]
                errors_history.append(last_errors.copy())
                if attempt_index == self._max_attempts - 1:
                    message = "LLM scoring produced invalid JSON after retries"
                    if parse_exc is not None:
                        raise ValueError(message) from parse_exc
                    raise ValueError(message)
                continue

            validation_errors = self._validator.validate(parsed_response)
            if validation_errors:
                last_errors = validation_errors
                errors_history.append(validation_errors.copy())
                if attempt_index == self._max_attempts - 1:
                    joined = "; ".join(validation_errors)
                    raise ValueError(
                        f"LLM scoring response violated schema after retries: {joined}"
                    )
                continue

            diagnostics = RetryDiagnostics(
                attempts=attempt_index + 1,
                schema_errors=errors_history.copy(),
                prompt_augmented=attempt_index > 0 and bool(errors_history),
            )
            return parsed_response, diagnostics

        raise ValueError("LLM scoring failed: empty response payload")

    @staticmethod
    def _coerce_to_mapping(
        raw_response: Any,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[Exception]]:
        if isinstance(raw_response, Mapping):
            return dict(raw_response), None, None
        if isinstance(raw_response, str):
            try:
                return json.loads(raw_response), None, None
            except json.JSONDecodeError as exc:
                return None, f"JSON parse error: {exc}", exc
        return None, f"Unexpected response type: {type(raw_response).__name__}", None


@dataclass
class ScoreBreakdown:
    score: float
    breakdown: Dict[str, float]


@dataclass
class DocumentationScore(ScoreBreakdown):
    raw: float = 0.0


class ScoreNormalizer:
    def __init__(self, response: Mapping[str, Any], candidate: Mapping[str, Any]):
        self._response = response
        self._candidate = candidate

    def bio(self) -> ScoreBreakdown:
        score, breakdown = _score_from_response(
            self._response,
            ("bio_subscores", "bio_subcriteria", "bio_components"),
            _BIO_KEYS,
        )
        return ScoreBreakdown(
            score=score,
            breakdown=self._coerce_breakdown_dict(breakdown, _BIO_KEYS),
        )

    def documentation(self) -> DocumentationScore:
        raw_score, breakdown = _score_from_response(
            self._response,
            (
                "documentation_subscores",
                "documentation_subcriteria",
                "documentation_components",
            ),
            _DOC_KEYS,
        )
        breakdown_dict = self._coerce_breakdown_dict(breakdown, _DOC_KEYS)
        weighted = _documentation_score_v2(breakdown_dict, raw_score)
        return DocumentationScore(
            score=weighted,
            breakdown=breakdown_dict,
            raw=raw_score,
        )

    def confidence(self) -> float:
        confidence_value = _coerce_float(self._response.get("confidence_score"))
        if confidence_value is None:
            confidence_value = 0.0
        return clamp_score(confidence_value)

    def publication_ids(self) -> List[str]:
        raw_publications = self._response.get("publication_ids")
        publications: List[str] = []
        if isinstance(raw_publications, str):
            stripped = raw_publications.strip()
            if stripped:
                publications = [stripped]
        elif isinstance(raw_publications, Sequence):
            publications = [
                str(item).strip() for item in raw_publications if str(item).strip()
            ]

        if not publications:
            fallback = self._candidate.get("publication_ids") or []
            publications = [str(item).strip() for item in fallback if str(item).strip()]
        return publications

    def homepage(self) -> str:
        for option in (
            self._response.get("homepage"),
            _candidate_homepage(self._candidate),
        ):
            if isinstance(option, str):
                stripped = option.strip()
                if stripped and not is_probable_publication_url(stripped):
                    return stripped
        return ""

    def tool_name(self) -> str:
        return (
            self._response.get("tool_name")
            or self._candidate.get("title")
            or self._candidate.get("name", "")
        )

    def concise_description(self) -> str:
        return self._response.get("concise_description", "")

    def rationale(self) -> str:
        return self._response.get("rationale", "")

    @staticmethod
    def _coerce_breakdown_dict(
        breakdown: Union[Mapping[str, Any], Sequence[Any], None],
        canonical_order: Sequence[str],
    ) -> Dict[str, float]:
        if isinstance(breakdown, Mapping):
            result: Dict[str, float] = {}
            for key in canonical_order:
                value = _coerce_float(breakdown.get(key))
                result[key] = float(value) if value is not None else 0.0
            for extra_key, extra_value in breakdown.items():
                if extra_key in result:
                    continue
                coerced = _coerce_float(extra_value)
                if coerced is not None:
                    result[str(extra_key)] = float(coerced)
            return result
        if isinstance(breakdown, Sequence) and not isinstance(breakdown, (str, bytes)):
            result = {}
            for idx, key in enumerate(canonical_order):
                value = _coerce_float(breakdown[idx]) if idx < len(breakdown) else None
                result[key] = float(value) if value is not None else 0.0
            return result
        return {key: 0.0 for key in canonical_order}


class Scorer:
    def __init__(self, model=None, config=None):
        self.config = config or get_config_yaml()
        self.client = OllamaClient(config=self.config)
        self.model = model or self.config.get("ollama", {}).get("model")
        self.prompt_builder = PromptBuilder(self.config)
        self._schema_validator = SchemaValidator()

    def score_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Score a candidate using LLM with proper error handling."""
        if not isinstance(candidate, dict):
            raise ValueError("Candidate must be a dictionary")

        if not candidate.get("title") and not candidate.get("name"):
            raise ValueError("Candidate must have either 'title' or 'name' field")

        base_prompt = self._build_prompt(candidate)
        origin_types = self._origin_types(candidate)

        retry_manager = LLMRetryManager(
            client=self.client,
            model=self.model,
            validator=self._schema_validator,
            schema_retries=self._schema_retries(),
        )
        response_payload, diagnostics = retry_manager.run(
            base_prompt, self.prompt_builder
        )

        normalizer = ScoreNormalizer(response_payload, candidate)
        bio_score = normalizer.bio()
        documentation_score = normalizer.documentation()

        model_params = diagnostics.to_model_params()

        result = {
            "tool_name": normalizer.tool_name(),
            "homepage": normalizer.homepage(),
            "publication_ids": normalizer.publication_ids(),
            "bio_score": bio_score.score,
            "documentation_score": documentation_score.score,
            "concise_description": normalizer.concise_description(),
            "rationale": normalizer.rationale(),
            "model": self.model,
            "model_params": model_params,
            "origin_types": origin_types,
            "confidence_score": normalizer.confidence(),
        }

        result["bio_subscores"] = bio_score.breakdown
        result["documentation_subscores"] = documentation_score.breakdown

        if documentation_score.raw != documentation_score.score:
            result["documentation_score_raw"] = documentation_score.raw
        result["doc_score_v2"] = documentation_score.score
        result["documentation_score"] = documentation_score.score

        return result

    def _schema_retries(self) -> int:
        raw_schema_retries = self.config.get("ollama", {}).get("schema_retries", 1)
        try:
            schema_retries = int(raw_schema_retries)
        except (TypeError, ValueError):
            schema_retries = 1
        return max(0, schema_retries)

    def _build_prompt(self, candidate: dict) -> str:
        return self.prompt_builder.build(candidate)

    def _augment_prompt_with_errors(
        self, base_prompt: str, errors: Sequence[str]
    ) -> str:
        return self.prompt_builder.augment(base_prompt, errors)

    def _origin_types(self, candidate: dict) -> list[str]:
        return PromptBuilder.origin_types(candidate)
