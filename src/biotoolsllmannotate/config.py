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
        "registry_path": None,
        "payload_version": __version__,
        "resume_from_enriched": False,
        "from_date": "7d",
        "to_date": None,
        "resume_from_pub2tools": False,
        "resume_from_scoring": False,
        "bio_score_thresholds": {
            "add": 0.6,
            "review": 0.5,
        },
        "documentation_score_thresholds": {
            "add": 0.6,
            "review": 0.5,
        },
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

Note: The documentation keywords and found keywords listed above were automatically mined from the homepage, papers, and other reference material. Their raw surrounding text is not included here except for the publication abstract and publication full text fields above. Treat the keywords as secondary hints, use the abstract/full_text as primary evidence when they contain concrete statements, and always cite the specific source (abstract, full_text, keyword) when referenced. When both abstract and full_text are present, prefer full_text > abstract > homepage/documentation > repository > keyword hints.

Decision context: Downstream acceptance requires the averaged bio score and the averaged documentation score to meet or exceed 0.5. Your scoring should therefore reject (keep scores below 0.5) any resource that fails the gating checklist or lacks solid evidence in either rubric group.

Gating checklist (apply before scoring):

Life-science scope — if the material does not clearly describe a life-science or biomedical purpose, set bio_subscores A1–A5 = 0, documentation_subscores B1–B5 = 0, confidence_score ≤ 0.2, and begin the rationale with "Rejected as bio.tools candidate because domain is non-bio".

Usable software deliverable — if the resource is only a dataset, publication, benchmark, ontology/specification, tutorial/course, or otherwise lacks a runnable interface (CLI with usage, installable package, container, web/desktop app, API, or executable workflow with steps), set A1–A5 = 0, B1–B5 = 0, confidence_score ≤ 0.2, and state "Rejected ... because no usable software deliverable".

Operational access & documentation — if the homepage status is ≥ 400, homepage_error is non-empty, or no explicit documentation artifacts are present (see B1–B5 definitions), set all B-subscores to 0, mark each missing item as "insufficient evidence", and cap confidence_score at 0.3. If the homepage is reachable but provides only generic marketing text without concrete artifacts, treat documentation evidence as missing.

Task:
Assuming the resource passes the relevant gates, score every subcriterion using exactly one of {{0, 0.5, 1}}. Use only the provided material; do not invent facts or URLs. Award ≥0.5 only when you can point to a specific artifact; award 1.0 only when there is corroboration from at least two distinct artifacts/sources.

Bio score rubric
A1 Biological intent stated (explicit life-science task/domain).
• 1 = explicit bio intent named (e.g., variant calling, single-cell clustering, protein ID).
• 0.5 = biology is mentioned but task/domain is vague.
• 0 = no clear life-science intent.

A2 Operations on biological data described.
• 1 = concrete bio data operations or pipelines are described (e.g., align FASTQ to reference; identify peptides from mzML).
• 0.5 = claims to process biological data but lacks concrete steps.
• 0 = no operational description.

A3 Software with biological data I/O:
• 1 = concrete datatypes/formats or endpoints named (e.g., FASTQ/BAM/VCF/GFF/GTF/BED; mzML/mzIdentML/mzTab/MGF/Thermo RAW; PDB/mmCIF; h5ad/loom/MTX/Seurat; REST endpoints/OpenAPI).
• 0.5 = only generic “data/files/CSV” mentions.
• 0 = none.

A4 Modality explicitly classifiable as one or more of: database portal, desktop application, web application, web API, web service, SPARQL endpoint, command-line tool (CLI), workbench, suite, plug-in, workflow, library.
• 1 = modality named AND minimal usage/access context shown (e.g., command example, URL path for API, “conda install …” then tool subcommand).
• 0.5 = modality named but no concrete access/usage context.
• 0 = not classifiable.

A5 Evidence of bio use (real-data examples or peer-reviewed/benchmark citation).
• 1 = at least one peer-reviewed citation (DOI/PMID/PMCID in publication_ids/abstract/full_text) OR an example/benchmark explicitly using biological data.
• 0.5 = claimed evaluation without clear citation or example.
• 0 = none.

Documentation score rubric (subcriteria only; no overall score here)
B1 Documentation completeness — presence of a user-oriented guide (docs/manual/tutorial/how-to/usage/walkthrough) or Usage:/--help.
• 1 = two or more independent artifacts (e.g., docs site + README usage section).
• 0.5 = exactly one concrete artifact.
• 0 = only keywords/hints or nothing.

B2 Installation pathways — package managers (pip/conda/bioconda/Bioconductor/CRAN/brew/apt) or containers (Docker/Singularity/Apptainer/BioContainers) or reproducible environment files.
• 1 = two or more independent install options (e.g., Bioconda + Docker).
• 0.5 = exactly one concrete install/container instruction.
• 0 = none or keyword-only.

B3 Reproducibility aids — versioned releases/tags/changelog/DOI and/or explicit, copyable commands/workflows or test data.
• 1 = versioning artifact (release/tag/DOI/changelog) AND one additional reproducibility artifact (e.g., exact commands/test data).
• 0.5 = exactly one qualifying artifact.
• 0 = none.

B4 Maintenance signal — evidence of maintenance or support channels (recent release/commit ≤ 3 years, active issues/roadmap/news).
• 1 = recent activity plus a support channel (issues/discussions/roadmap).
• 0.5 = either recent activity or a support channel, but not both.
• 0 = none.

B5 Onboarding & support — FAQ/troubleshooting/contact/community/contributing/code of conduct.
• 1 = two or more distinct onboarding/support artifacts.
• 0.5 = exactly one.
• 0 = none.

Selection/normalization rules:

• Treat unreachable homepages (status ≥ 400 or any homepage_error text) as missing documentation and score every documentation subcriterion 0.
• Award 0.5 in any documentation subscore only when you can point to a specific artifact tied to one of the scraped keywords above (explicit URL/title/section, file path, quoted instruction, or repository section). Keyword hints alone score 0 and must be cited as "insufficient evidence: <keyword>" if no corroborating artifact exists.
• Award 1.0 in a documentation subscore only when two or more independent artifacts support that criterion. “Independent” means different sources or sections (e.g., docs site vs README; release page vs Zenodo DOI; Docker registry vs Bioconda).
• Tags and documentation keywords are extracted hints; cite them as "keyword evidence" when they support an explicit artifact that matches the scraped keyword list, but do not fabricate details beyond what is stated.
• Leverage the publication abstract and publication full text fields to substantiate life-science scope, software modality, evidence of bio use, and documentation artifacts. Cite them explicitly as "abstract" or "full_text" in the rationale, and only award documentation credit from these sources when they contain concrete actionable statements (e.g., installation steps, usage walkthroughs, named manuals).
• Normalize publication identifiers to prefixes: DOI:..., PMID:..., PMCID:... and remove duplicates (case-insensitive).
• For any subcriterion scored 0 due to missing evidence, mention "insufficient evidence: <item>" in the rationale.
• Negative cues (dataset/benchmark-only, portal/KB without tool interface, review/survey/manuscript only, ontology/spec only, course/tutorial only) should push A4/B2/B1 toward 0 unless a runnable interface or install path is explicitly evidenced.

Rationale requirements:
• When any gating failure forces zeroed scores, start the rationale with "Rejected as bio.tools candidate because ..." and describe the failing gate.
• For accepted resources (expected to exceed the 0.5 downstream thresholds), highlight at least two distinct documentation artifacts (e.g., "Bioconda install" and "Docker image") and the key biological use evidence (format/task or citation). Downgrade confidence to ≤ 0.7 if fewer than two artifacts are confirmed, even if other scores are high.

Confidence calibration guidelines (adjust intermediate values as needed):

0.9–1.0 only when every applicable subcriterion is fully satisfied with explicit evidence from multiple sources (homepage, documentation, repository, publications) and documentation subscores are supported by two or more artifacts each.

0.6–0.8 when most evidence is strong but one or two subcriteria rely on single artifacts or weaker hints; call out the weaker areas in the rationale.

0.3–0.5 when evidence is mixed, incomplete, or primarily keyword-level with limited direct verification.

0.0–0.2 when information is insufficient, conflicting, or lacks primary sources—explicitly note "insufficient evidence" items in the rationale.

Confidence must be ≤ 0.5 whenever any documentation subscore relies solely on keyword evidence or the homepage is unreachable.

Do NOT compute aggregate scores; only fill the provided fields.
Do not output any value outside [0.0, 1.0].
Always emit every field in the output JSON exactly once.
Keep field names like `bio_subscores` and `documentation_subscores` exactly as spelled.
Do not default to 0.9 confidence; calibrate strictly per the guidance above.
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
"confidence_score": <0–1 numeric confidence>,
"concise_description": "<1–2 sentence rewritten summary>",
"rationale": "<2–5 sentences citing specific evidence for both score groups; for each claim indicate the source as one of: homepage, documentation, repository, abstract, full_text, tags; explicitly name missing items as 'insufficient evidence: ...'>"
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
