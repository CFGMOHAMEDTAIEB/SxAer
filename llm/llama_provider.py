import json
import os
import urllib.request
import time


class LlamaProvider:
	def __init__(self, endpoint=None, model=None, timeout=30, retries=2):
		self.endpoint = endpoint or os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
		self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2")
		self.timeout, self.retries = timeout, retries

	def complete(self, prompt: str) -> str:
		payload = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode()
		request = urllib.request.Request(self.endpoint.rstrip("/") + "/api/generate", payload, {"Content-Type": "application/json"})
		last_error = None
		for attempt in range(self.retries + 1):
			try:
				with urllib.request.urlopen(request, timeout=self.timeout) as response:
					return json.loads(response.read()).get("response", "")
			except Exception as exc:
				last_error = exc
				if attempt < self.retries:
					time.sleep(0.2 * (attempt + 1))
		raise RuntimeError(f"Ollama request failed: {last_error}") from last_error

	def connection_test(self) -> dict:
		self.complete("Return the word OK.")
		return {"ok": True, "provider": "ollama", "model": self.model}
