"""Async HTTP client for the Noesis REST API with actionable, agent-readable error messages."""
import os

import httpx


class NoesisAPIError(Exception):
    """Message is written for an LLM agent: what failed and what to do next."""


class NoesisClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, api_key: str | None = None, http: httpx.AsyncClient | None = None):
        self.base = (base_url or os.getenv("NOESIS_URL", "http://localhost:8000")).rstrip("/")
        self.token = token if token is not None else os.getenv("NOESIS_TOKEN", "")
        self.api_key = api_key if api_key is not None else os.getenv("NOESIS_API_KEY", "")
        self._http = http

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=60, trust_env=False)
        return self._http

    def _headers(self) -> dict:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    async def request(self, method: str, path: str, **kw):
        url = f"{self.base}/api/v1{path}"
        try:
            r = await self.http.request(method, url, headers=self._headers(), **kw)
        except httpx.ConnectError:
            raise NoesisAPIError(f"Cannot reach Noesis at {self.base}. Start it with `python -m noesis.cli serve`, or set NOESIS_URL.")
        except httpx.TimeoutException:
            raise NoesisAPIError("Noesis did not answer in time. Long work runs as jobs: start one (noesis_ask_question) and poll noesis_get_job.")
        if r.status_code < 300:
            return r.json()
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text[:200]
        if r.status_code == 401:
            raise NoesisAPIError("Authentication failed. Set NOESIS_TOKEN (from POST /api/v1/auth/login) or NOESIS_API_KEY for this MCP server.")
        if r.status_code == 403:
            raise NoesisAPIError(f"Not allowed: {detail}. This action needs an admin account.")
        if r.status_code == 404:
            raise NoesisAPIError(f"Not found: {detail}. List valid ids with noesis_list_projects / noesis_get_beliefs first.")
        if r.status_code == 409 and isinstance(detail, dict):
            raise NoesisAPIError(f"{detail.get('message')}. Poll noesis_get_job with job_id={detail.get('job_id')} instead of starting another.")
        if r.status_code == 413:
            raise NoesisAPIError(f"{detail}. Split the document or upload a smaller file.")
        if r.status_code == 422:
            raise NoesisAPIError(f"Invalid input: {detail if isinstance(detail, str) else str(detail)[:400]}")
        if r.status_code == 429:
            raise NoesisAPIError(f"Rate limited by Noesis. Retry in {r.headers.get('Retry-After', '60')} seconds; avoid starting many jobs at once.")
        raise NoesisAPIError(f"Noesis returned HTTP {r.status_code}: {str(detail)[:300]}")
