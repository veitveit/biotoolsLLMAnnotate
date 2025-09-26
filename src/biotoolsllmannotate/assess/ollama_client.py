import requests

from biotoolsllmannotate.config import get_config_yaml


class OllamaClient:
    """Wrapper for interacting with local Ollama LLM server."""

    def __init__(self, base_url=None, config=None):
        self.config = config or get_config_yaml()
        self.base_url = base_url or self.config.get("ollama", {}).get("host")

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
                return match.group(0)
            raise ValueError("No valid JSON object found in Ollama response")

        return _call()
