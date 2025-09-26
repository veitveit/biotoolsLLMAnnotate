import json
from datetime import UTC, datetime
from pathlib import Path

import requests

from biotoolsllmannotate.config import get_config_yaml


class OllamaClient:
    """Wrapper for interacting with local Ollama LLM server."""

    def __init__(self, base_url=None, config=None):
        self.config = config or get_config_yaml()
        self.base_url = base_url or self.config.get("ollama", {}).get("host")
        log_path = (self.config.get("logging", {}) or {}).get("llm_log")
        self.llm_log_path = Path(log_path) if log_path else Path("out/ollama.log")

    def generate(self, prompt, model=None, temperature=0.1, top_p=1.0, seed=None):
        import re

        from tenacity import retry, stop_after_attempt, wait_fixed

        max_attempts = self.config.get("max_attempts", 3)
        backoff = self.config.get("backoff_seconds", 2)

        @retry(stop=stop_after_attempt(max_attempts), wait=wait_fixed(backoff))
        def _call():
            payload = {
                "model": model or self.config.get("ollama_model"),
                "prompt": prompt,
                "temperature": temperature,
                "top_p": top_p,
            }
            if seed is not None:
                payload["seed"] = seed
            resp = requests.post(
                f"{self.base_url}/api/generate", json=payload, timeout=300
            )
            resp.raise_for_status()
            combined = ""
            for line in resp.text.strip().splitlines():
                try:
                    import json

                    obj = json.loads(line)
                    if isinstance(obj, dict) and "response" in obj:
                        combined += obj["response"]
                except Exception:
                    continue
            match = re.search(r"\{.*?\}", combined, re.DOTALL)
            if match:
                final_json = match.group(0)
                self._log_exchange(payload, final_json, is_json=True)
                return match.group(0)
            self._log_exchange(payload, combined, is_json=False)
            raise ValueError("No valid JSON object found in Ollama response")

        return _call()

    def _log_exchange(self, payload, response_text, *, is_json: bool):
        try:
            self.llm_log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(UTC).isoformat()
            with self.llm_log_path.open("a", encoding="utf-8") as f:
                f.write("==== BEGIN OLLAMA REQUEST\n")
                f.write(f"timestamp: {timestamp}\n")
                f.write(json.dumps(payload, ensure_ascii=False, indent=2))
                f.write("\n---- RESPONSE\n")
                if is_json:
                    try:
                        parsed = json.loads(response_text)
                        pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
                    except Exception:
                        pretty = response_text
                else:
                    pretty = response_text
                if not pretty.endswith("\n"):
                    pretty += "\n"
                f.write(pretty)
                f.write("==== END OLLAMA REQUEST\n\n")
        except Exception:
            pass
