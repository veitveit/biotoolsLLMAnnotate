import json
from pathlib import Path
from typing import Any


class ReportWriter:
    def write_report(self, report_lines: list[dict[str, Any]], file_path: str) -> None:
        """Write a JSONL report: one JSON object per line.
        """
        with open(Path(file_path), "w") as f:
            for line in report_lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def summarize_report(
        self, report_lines: list[dict[str, Any]], file_path: str
    ) -> None:
        """Write a human-readable summary (Markdown) of the assessment report.
        """
        lines = [
            "# Assessment Summary\n",
            "| Tool | Bio Score | Documentation | Decision | Rationale |",
            "|------|-----------|---------------|----------|-----------|",
        ]
        for r in report_lines:
            tool = r.get("title") or r.get("name") or "?"
            # Accept either flattened or nested score structures
            scores = r.get("scores") if isinstance(r.get("scores"), dict) else r
            bio_score = scores.get("bio_score") if isinstance(scores, dict) else None
            documentation_score = (
                scores.get("documentation_score") if isinstance(scores, dict) else None
            )
            bio_fmt = f"{bio_score:.2f}" if isinstance(bio_score, (int, float)) else ""
            docs_fmt = (
                f"{documentation_score:.2f}"
                if isinstance(documentation_score, (int, float))
                else ""
            )
            decision = str(r.get("decision", r.get("include", "?")))
            rationale = (
                scores.get("rationale", "")
                if isinstance(scores, dict)
                else r.get("rationale", "")
            )
            rationale = rationale.replace("|", " ")[:80] + (
                "..." if len(rationale) > 80 else ""
            )
            lines.append(
                f"| {tool} | {bio_fmt} | {docs_fmt} | {decision} | {rationale} |"
            )
        with open(Path(file_path), "w") as f:
            f.write("\n".join(lines) + "\n")
