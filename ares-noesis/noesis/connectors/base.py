"""Connector abstraction: rate limit, retry/backoff, cache, provenance, license tracking."""
import hashlib
import re
import time
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel, Field

from ..config import get_settings


class ConnectorUnavailable(Exception):
    def __init__(self, connector: str, reason: str):
        super().__init__(f"{connector}: {reason}")
        self.connector, self.reason = connector, reason


class ConnectorError(Exception):
    pass


class Paper(BaseModel):
    source: str
    source_id: str = ""
    title: str
    abstract: str = ""
    doi: str = ""
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str = ""
    url: str = ""
    open_access_pdf: str = ""
    license: str = ""
    retracted: bool | None = None
    is_preprint: bool = False
    cited_by: int | None = None
    pub_types: list[str] = Field(default_factory=list)
    sample_size: int | None = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def content_hash(self) -> str:
        key = self.doi.lower().strip() or re.sub(r"\W+", " ", self.title.lower()).strip()
        return hashlib.sha256(key.encode()).hexdigest()

    @property
    def first_author_surname(self) -> str:
        return self.authors[0].split()[-1].lower() if self.authors else ""


class BaseConnector:
    name = "base"
    terms_url = ""
    license_note = ""
    requires_auth = False
    min_interval = 0.2

    def __init__(self, settings=None, client: httpx.Client | None = None, sleep=time.sleep):
        self.settings = settings or get_settings()
        self._client = client
        self._sleep = sleep
        self._last = 0.0
        self._cache: dict = {}

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            ua = f"Noesis/0.1 (mailto:{self.settings.contact_email})" if self.settings.contact_email else "Noesis/0.1"
            self._client = httpx.Client(timeout=self.settings.http_timeout, headers={"User-Agent": ua}, follow_redirects=False)
        return self._client

    def available(self) -> tuple[bool, str]:
        if self.settings.offline:
            return False, "offline mode"
        return True, ""

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None, retries: int = 3):
        ok, why = self.available()
        if not ok:
            raise ConnectorUnavailable(self.name, why)
        key = (url, tuple(sorted((params or {}).items())))
        if key in self._cache:
            return self._cache[key]
        for attempt in range(retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            delay = 0.5 * 2 ** attempt
            try:
                r = self.client.get(url, params=params, headers=headers)
            except httpx.HTTPError:
                r = None
            if r is not None:
                if r.status_code == 200:
                    self._cache[key] = r
                    return r
                if r.status_code in (429, 500, 502, 503, 504):
                    try:
                        delay = float(r.headers.get("Retry-After", delay))
                    except ValueError:
                        pass
                else:
                    raise ConnectorError(f"{self.name}: HTTP {r.status_code}")
            if attempt < retries:
                self._sleep(delay)
        raise ConnectorUnavailable(self.name, "retries exhausted (network error or rate limit)")

    def _post(self, url: str, body: dict, headers: dict | None = None, retries: int = 3):
        """POST JSON with the same rate limit / backoff / error policy as _get."""
        ok, why = self.available()
        if not ok:
            raise ConnectorUnavailable(self.name, why)
        for attempt in range(retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            delay = 0.5 * 2 ** attempt
            try:
                r = self.client.post(url, json=body, headers=headers)
            except httpx.HTTPError:
                r = None
            if r is not None:
                if r.status_code == 200:
                    return r
                if r.status_code in (429, 500, 502, 503, 504):
                    try:
                        delay = float(r.headers.get("Retry-After", delay))
                    except ValueError:
                        pass
                else:
                    raise ConnectorError(f"{self.name}: HTTP {r.status_code}")
            if attempt < retries:
                self._sleep(delay)
        raise ConnectorUnavailable(self.name, "retries exhausted (network error or rate limit)")

    def search(self, query: str, limit: int = 5, page: int = 1) -> list[Paper]:
        raise NotImplementedError

    def describe(self) -> dict:
        ok, why = self.available()
        return {"name": self.name, "terms_url": self.terms_url, "license_note": self.license_note,
                "requires_auth": self.requires_auth, "available": ok, "reason": why}
