import json
import os
import time
import urllib.request


class GPTProvider:
	"""OpenAI-compatible provider; Azure OpenAI is supported by endpoint shape."""
	def __init__(self, endpoint=None, api_key=None, model=None, api_version=None, timeout=30, retries=2):
		self.endpoint = endpoint or os.getenv("SMARTX_LLM_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
		self.api_key = api_key or os.getenv("SMARTX_LLM_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
		self.model = model or os.getenv("SMARTX_LLM_MODEL", "gpt-4o-mini")
		self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
		self.timeout, self.retries = timeout, retries

	def complete(self, prompt: str) -> str:
		if not self.endpoint or not self.api_key:
			raise RuntimeError("OpenAI-compatible endpoint/API key not configured")
		url = self.endpoint.rstrip("/")
		if "azure.com" in url and "api-version" not in url:
			url += f"/openai/deployments/{self.model}/chat/completions?api-version={self.api_version}"
		elif not url.endswith("/chat/completions"):
			url += "/v1/chat/completions"
		payload = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}]}).encode()
		request = urllib.request.Request(url, payload, {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}", "api-key": self.api_key})
		last_error = None
		for attempt in range(self.retries + 1):
			try:
				with urllib.request.urlopen(request, timeout=self.timeout) as response:
					return json.loads(response.read())["choices"][0]["message"]["content"]
			except Exception as exc:
				last_error = exc
				if attempt < self.retries:
					time.sleep(0.2 * (attempt + 1))
		raise RuntimeError(f"LLM provider request failed: {last_error}") from last_error

	def connection_test(self) -> dict:
		self.complete("Return the word OK.")
		return {"ok": True, "provider": "openai-compatible"}
