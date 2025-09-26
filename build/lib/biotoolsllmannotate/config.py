import os
import yaml
from pathlib import Path

DEFAULT_CONFIG_YAML = {
    "pub2tools": {
        "edam_owl": "http://edamontology.org/EDAM.owl",
        "idf": "https://github.com/edamontology/edammap/raw/master/doc/biotools.idf",
        "idf_stemmed": "https://github.com/edamontology/edammap/raw/master/doc/biotools.stemmed.idf",
        "from_date": "7d",
        "to_date": None,
        "firefox_path": None,
        "p2t_cli": None,
        "custom_restriction": "SRC:MED OR SRC:PMC",
        "disable_tool_restriction": True,
        "timeout": 6000,
        "retryLimit": 0,
        "fetcher_threads": 4,
        "to_biotools_file": None,
    },
    "pipeline": {
        "from_date": "7d",
        "to_date": None,
        "min_score": 0.6,
        "limit": None,
        "dry_run": False,
        "output": "out/payload.json",
        "report": "out/report.jsonl",
        "model": "llama3.2",
        "concurrency": 8,
        "input_path": None,
        "offline": False,
        "updated_entries": "out/updated_entries.json",
        "payload_version": "0.8.1",
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
        }
    },
    "scoring_prompt_template": """Please evaluate this bioinformatics tool candidate for inclusion in bio.tools.\n\nTool Information:\n- Title: {title}\n- Description: {description}\n- Homepage: {homepage}\n- Documentation: {documentation}\n- Repository: {repository}\n- Tags: {tags}\n- Published: {published_at}\n- Publication Abstract: {publication_abstract}\n- Publication Full Text: {publication_full_text}\n\nPlease provide a JSON response with:\n- tool_name: The most appropriate display name for the tool (derive from the context if missing).\n- homepage: The best homepage URL for the tool (choose from the provided URLs if necessary).\n- publication_ids: A list of identifiers (e.g., PMID:xxxx, PMCID:xxxx, DOI:xxxx) relevant to the tool.\n- bio_score: A score from 0.0 to 1.0 indicating whether this is a bioinformatics tool or resource.\n- documentation_score: A score from 0.0 to 1.0 capturing if the available documentation makes the tool usable.\n- concise_description: A refined 1-2 sentence summary of the tool (avoid copying verbatim unless already concise).\n- rationale: A brief explanation referencing evidence for your scores.\n\nRespond ONLY with the JSON object. Response format: {{\"tool_name\": \"Example Tool\", \"homepage\": \"https://example.org\", \"publication_ids\": [\"pmid:12345\"], \"bio_score\": 0.8, \"documentation_score\": 0.9, \"concise_description\": \"Short rewritten summary.\", \"rationale\": \"This is a bioinformatics tool...\"}}""",
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

    # If none found, return the most likely path
    return str(current_file.parent.parent.parent.parent.parent.parent / "config.yaml")


def load_yaml_config(path=None):
    """Load config from YAML file, falling back to defaults."""
    if path is None:
        path = get_default_config_path()

    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except Exception:
        return DEFAULT_CONFIG_YAML.copy()


def get_config_yaml(config_path=None):
    """
    Load config from YAML file, falling back to defaults.

    Args:
        config_path: Optional path to config file. If None, uses default path.
    """
    config = load_yaml_config(config_path)
    return config or DEFAULT_CONFIG_YAML.copy()
