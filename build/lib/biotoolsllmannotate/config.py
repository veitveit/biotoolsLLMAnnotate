import os
import yaml
from pathlib import Path

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
        "to_biotools_file": None,
        "from_date": "7d",
        "to_date": None,
    },
    "pipeline": {
        "output": "out/exports/biotools_payload.json",
        "report": "out/reports/assessment.jsonl",
        "model": "llama3.2",
        "concurrency": 8,
        "input_path": None,
        "updated_entries": "out/exports/biotools_entries.json",
        "payload_version": "0.8.2",
        "enriched_cache": "out/cache/enriched_candidates.json.gz",
        "resume_from_enriched": False,
    },
    "ollama": {
        "host": "http://localhost:11434",
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
            "user_agent": "biotoolsllmannotate/0.8.2 (+https://github.com/ELIXIR-Belgium/biotoolsLLMAnnotate)",
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
Record each bio subcriterion as numbers {{0,0.5,1}} in bio_subscores and each documentation subcriterion as numbers {{0,0.5,1}} in documentation_subscores.
Emit ONLY the fields in the schema below. Use "" for unknown strings and [] if no publication identifiers are found. Do not output booleans/strings instead of numbers.

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
    final_config = config or DEFAULT_CONFIG_YAML.copy()
    
    if validate:
        # Import here to avoid circular imports
        try:
            from .validation import validate_and_raise
            validate_and_raise(final_config)
        except ImportError:
            # Validation module not available, skip validation
            pass
    
    return final_config
