import httpx
import pytest

from noesis.config import Settings
from noesis.connectors.base import ConnectorError, ConnectorUnavailable
from noesis.connectors.sources import NasaAdsConnector, OpenAlexConnector
from tests.conftest import EXTERNAL, mock_connectors, openalex_json


def test_openalex_parsing_and_provenance():
    c = mock_connectors()["openalex"]
    ps = c.search("graphene battery", 5)
    assert ps[0].title.startswith("Graphene coating") and ps[0].doi == "10.1/a"
    assert "graphene coating increases" in ps[0].abstract.lower()
    assert ps[0].license == "cc-by" and ps[0].source == "openalex" and ps[0].retrieved_at


def test_retry_with_exponential_backoff_then_success():
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=openalex_json(EXTERNAL))

    c = OpenAlexConnector(Settings(offline=False), client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=sleeps.append)
    c.min_interval = 0
    assert len(c.search("x")) == 3
    assert len(calls) == 3 and [round(s, 2) for s in sleeps if s >= 0.5] == [0.5, 1.0]


def test_rate_limit_retry_after_respected_and_exhaustion():
    sleeps = []
    c = OpenAlexConnector(Settings(offline=False), client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429, headers={"Retry-After": "2"}))), sleep=sleeps.append)
    c.min_interval = 0
    with pytest.raises(ConnectorUnavailable, match="retries exhausted"):
        c.search("x")
    assert 2.0 in sleeps


def test_client_error_is_not_retried():
    n = []
    c = OpenAlexConnector(Settings(offline=False), client=httpx.Client(transport=httpx.MockTransport(lambda r: (n.append(1), httpx.Response(404))[1])), sleep=lambda s: None)
    with pytest.raises(ConnectorError):
        c.search("x")
    assert len(n) == 1


def test_cache_prevents_repeat_requests():
    n = []
    c = OpenAlexConnector(Settings(offline=False), client=httpx.Client(transport=httpx.MockTransport(lambda r: (n.append(1), httpx.Response(200, json=openalex_json(EXTERNAL)))[1])), sleep=lambda s: None)
    c.min_interval = 0
    c.search("same"); c.search("same")
    assert len(n) == 1


def test_offline_and_missing_token_are_reported_not_faked():
    with pytest.raises(ConnectorUnavailable, match="offline"):
        OpenAlexConnector(Settings(offline=True)).search("x")
    ads = NasaAdsConnector(Settings(ads_token="", offline=False))
    assert ads.available() == (False, "NOESIS_ADS_TOKEN not configured")
    with pytest.raises(ConnectorUnavailable, match="ADS_TOKEN"):
        ads.search("x")


def test_paper_dedupe_hash_prefers_doi():
    a, b, _ = mock_connectors()["openalex"].search("q")
    assert a.content_hash != b.content_hash
