import copy
import os
import yaml
from pathlib import Path

from .version import __version__


def _replace_version_placeholders(value):
    if isinstance(value, dict):
        return {k: _replace_version_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_version_placeholders(item) for item in value]
    if isinstance(value, str) and "__VERSION__" in value:
        return value.replace("__VERSION__", __version__)
    return value


DEFAULT_CONFIG_YAML = {
    "pub2tools": {
        "edam_owl": "http://edamontology.org/EDAM.owl",
        "idf": "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
        "idf_stemmed": "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
        "firefox_path": None,
        "p2t_cli": None,
        "custom_restriction": "SRC:MED OR SRC:PMC",
        "disable_tool_restriction": True,
        "timeout": 6000,
        "retryLimit": 0,
        "fetcher_threads": 4,
    },
    "pipeline": {
        "input_path": None,
        "payload_version": __version__,
        "resume_from_enriched": False,
        "from_date": "7d",
        "to_date": None,
        "resume_from_pub2tools": False,
        "resume_from_scoring": False,
        "min_bio_score": 0.6,
        "min_documentation_score": 0.6,
    },
    "ollama": {
        "host": "http://localhost:11434",
        "model": "llama3.2",
        "max_retries": 3,
        "retry_backoff_seconds": 2,
        "temperature": 0.01,
        "concurrency": 8,
    },
    "logging": {
        "level": "INFO",
        "file": None,
    },
    "enrichment": {
        "europe_pmc": {
            "enabled": True,
            "include_full_text": True,
            "max_publications": 1,
            "max_full_text_chars": 4000,
            "timeout": 15,
        },
        "homepage": {
            "enabled": True,
            "timeout": 8,
            "user_agent": f"biotoolsllmannotate/{__version__} (+https://github.com/ELIXIR-Belgium/biotoolsLLMAnnotate)",
        },
    },
    "scoring_prompt_template": """You are evaluating whether a software resource is worth getting registered in bio.tools, the registry for software resources in the life sciences.

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

Note: The documentation keywords and found keywords listed above were automatically mined from the homepage, papers, and other reference material whose raw text is not included in this prompt. Treat them as secondary hints and cite them explicitly when used.

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
Documentation links and keywords listed above are rubric-aligned evidence sources. Interpret them as:
• Installation pathways (B2): presence of urls or keywords such as install, installation, package, pip, conda, workflow → award ≥0.5; reach 1.0 when both keyword and explicit link are provided.
• Reproducibility aids (B3): release, version, tag, news, changelog in links/keywords → award ≥0.5; raise to 1.0 when multiple supporting signals exist.
• Maintenance signal (B4): commit, issues, activity, support, community, workflow → award ≥0.5; raise to 1.0 if both keyword and corresponding link (e.g. commits page) are present.
• Documentation completeness & onboarding (B1/B5): doc, docs, documentation, guide, manual, usage, faq, contact → award ≥0.5; raise to 1.0 when links confirm comprehensive material.
Explicitly cite the supporting keyword or link as "keyword evidence" when scoring.
Tags listed above are likewise extracted hints from the same external sources; cite them as "keyword evidence" when relevant but do not infer new facts beyond what is stated.
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
"rationale": "<2–5 sentences citing specific evidence for both score groups; for each claim indicate the source as one of: homepage, documentation, repository, abstract, full_text, tags; explicitly name missing items as 'insufficient evidence: ...'>>"
}}""",
}


def get_default_config_path():
    """Get the default config file path."""
    # First check for environment variable
    env_path = os.environ.get("BIOTOOLS_CONFIG")
    if env_path:
        return env_path

    # Try to find config.yaml in the project root
    # When running from source, __file__ is in src/biotoolsllmannotate/
    # When installed, we need to go up more levels
    current_file = Path(__file__)

    # Try different possible locations
    possible_paths = [
        # From source: src/biotoolsllmannotate/config.py -> project_root/config.yaml
        current_file.parent.parent.parent / "config.yaml",
        # From installed package: site-packages/biotoolsllmannotate/config.py -> project_root/config.yaml
        current_file.parent.parent.parent.parent.parent.parent / "config.yaml",
        # Fallback: current directory
        Path("config.yaml"),
    ]

    for path in possible_paths:
        if path.exists():
            return str(path)

    # Default fallback
    return "config.yaml"


def load_yaml_config(path=None):
    """Load config from YAML file, falling back to defaults."""
    if path is None:
        path = get_default_config_path()

    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except Exception:
        return DEFAULT_CONFIG_YAML.copy()


def get_config_yaml(config_path=None, validate=True):
    """
    Load config from YAML file, falling back to defaults.

    Args:
        config_path: Optional path to config file. If None, uses default path.
        validate: Whether to validate the configuration (default: True).
    """
    config = load_yaml_config(config_path)
    final_config = copy.deepcopy(DEFAULT_CONFIG_YAML) if not config else config
    final_config = _replace_version_placeholders(final_config)
    final_config = _replace_version_placeholders(final_config)

    if validate:
        # Import here to avoid circular imports
        try:
            from .validation import validate_and_raise

            validate_and_raise(final_config)
        except ImportError:
            # Validation module not available, skip validation
            pass

    return final_config
