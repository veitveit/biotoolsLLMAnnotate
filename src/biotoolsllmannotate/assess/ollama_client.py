import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from biotoolsllmannotate.config import get_config_yaml


class OllamaConnectionError(Exception):
    """Raised when Ollama service is unavailable."""
    pass


class OllamaClient:
    """Wrapper for interacting with local Ollama LLM server with connection pooling and retries."""

    def __init__(self, base_url=None, config=None):
        self.config = config or get_config_yaml()
        self.base_url = base_url or self.config.get("ollama", {}).get("host", "http://localhost:11434")
        log_path = self.config.get("logging", {}).get("llm_log")
        self.llm_log_path = Path(log_path) if log_path else Path("out/logs/ollama.log")
        
        # Setup session with connection pooling and retries
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({'Connection': 'keep-alive'})

    def generate(self, prompt, model=None, temperature=0.05, top_p=1.0, seed=None):
        from tenacity import retry, stop_after_attempt, wait_fixed

        max_attempts = self.config.get("max_attempts", 3)
        backoff = self.config.get("backoff_seconds", 2)

        @retry(stop=stop_after_attempt(max_attempts), wait=wait_fixed(backoff))
        def _call():
            payload = {
                "model": model or self.config.get("pipeline", {}).get("model"),
                "prompt": prompt,
                "temperature": temperature,
                "top_p": top_p,
            }
            if seed is not None:
                payload["seed"] = seed
            try:
                resp = self.session.post(
                    f"{self.base_url}/api/generate", 
                    json=payload, 
                    timeout=self.config.get("ollama_timeout", 300)
                )
                resp.raise_for_status()
            except requests.exceptions.HTTPError as e:
                if resp.status_code == 404 and "not found" in resp.text:
                    model_name = payload.get("model", "unknown")
                    raise OllamaConnectionError(f"Model '{model_name}' not found in Ollama. Available models: ollama list")
                raise OllamaConnectionError(f"Ollama HTTP error: {e}")
            except requests.exceptions.RequestException as e:
                raise OllamaConnectionError(f"Failed to connect to Ollama at {self.base_url}: {e}")
            combined = ""
            for line in resp.text.strip().splitlines():
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and "response" in obj:
                        combined += obj["response"]
                except Exception:
                    continue

            def _attempt_parse(text: str) -> str | None:
                start = text.find("{")
                end = text.rfind("}")
                if start == -1 or end == -1 or end <= start:
                    return None
                candidate = text[start : end + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    return None

            final_json = _attempt_parse(combined)
            if final_json is None:
                final_json = _attempt_parse(resp.text)

            if final_json is not None:
                self._log_exchange(payload, final_json, is_json=True)
                return final_json

            self._log_exchange(payload, combined, is_json=False)
            raise ValueError("No valid JSON object found in Ollama response")

        return _call()

    def ping(self) -> tuple[bool, Optional[str]]:
        """Check whether the Ollama endpoint is reachable."""
        try:
            resp = self.session.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            return True, None
        except requests.exceptions.ConnectionError:
            return False, f"Connection failed: Ollama service not available at {self.base_url}"
        except requests.exceptions.Timeout:
            return False, f"Timeout: Ollama service at {self.base_url} took too long to respond"
        except requests.exceptions.RequestException as exc:
            return False, f"Request failed: {exc}"
        except Exception as exc:
            return False, f"Unexpected error: {exc}"

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
