"""Minimal Anthropic Messages API client (httpx). Used for structured extraction only; never as a source of facts."""
import json
import re
import time

import httpx


class LLMError(Exception):
    pass


class LLMClient:
    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, settings, client: httpx.Client | None = None, sleep=time.sleep):
        self.settings = settings
        self._client = client
        self._sleep = sleep
        self.calls = 0

    def available(self) -> bool:
        return self._client is not None and bool(self.settings.llm_api_key) and not self.settings.offline

    def complete_json(self, system: str, user: str, max_tokens: int = 1500, retries: int = 2):
        if not self.available():
            raise LLMError("LLM not configured for an injected transport or offline")
        if self.calls >= self.settings.llm_max_calls:
            raise LLMError("per-document LLM call budget exhausted")
        body = {"model": self.settings.llm_model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self.settings.llm_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        last = "unknown"
        for attempt in range(retries + 1):
            self.calls += 1
            try:
                r = self._client.post(self.url, json=body, headers=headers)
            except httpx.HTTPError as e:
                last = f"network: {e}"
                r = None
            if r is not None:
                if r.status_code == 200:
                    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
                    try:
                        return parse_json(text)
                    except ValueError as e:
                        last = f"invalid JSON from model: {e}"
                elif r.status_code in (429, 500, 502, 503, 529):
                    last = f"HTTP {r.status_code}"
                else:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
            if attempt < retries:
                self._sleep(2 ** attempt)
        raise LLMError(last)


def parse_json(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", t, re.S)
        if not m:
            raise ValueError("no JSON found")
        return json.loads(m.group(0))
