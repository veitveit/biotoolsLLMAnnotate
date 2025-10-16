import copy
import os
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

# Ensure we import the in-repo CLI implementation even if an older installed
# package version was loaded earlier during the pytest session.
for module_name in ["biotoolsllmannotate.cli.main", "biotoolsllmannotate.cli"]:
    sys.modules.pop(module_name, None)

from biotoolsllmannotate.cli.main import app
from biotoolsllmannotate.config import DEFAULT_CONFIG_YAML


def test_conflicting_resume_and_input_exits_with_message(tmp_path):
    """Resume-from-pub2tools and explicit input conflict returns exit code 2."""
    config_data = copy.deepcopy(DEFAULT_CONFIG_YAML)
    pipeline_cfg = config_data.setdefault("pipeline", {})
    pipeline_cfg["input_path"] = "out/positives.json"
    pipeline_cfg["resume_from_pub2tools"] = True
    pipeline_cfg["resume_from_enriched"] = False
    pipeline_cfg["resume_from_scoring"] = False

    config_path = Path(tmp_path) / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["--config", str(config_path)])

    assert result.exit_code == 2
    output = result.output or ""
    assert "Invalid value for --resume-from-pub2tools" in output
    assert "pipeline.input_path" in output
    assert "Traceback" not in output
