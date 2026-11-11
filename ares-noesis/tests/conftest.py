import json

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from noesis.api.main import create_app
from noesis.config import Settings
from noesis.connectors.sources import (ArxivConnector, CrossrefConnector, EuropePMCConnector, NasaAdsConnector,
                                     OpenAlexConnector)
from noesis.db import make_engine, make_session_factory
from noesis.storage import LocalBlobStore

TEST_KEY = "testkey" * 5

DOC_TEXT = """Graphene coating improves battery lifespan under humid conditions
Abstract
We found that graphene coating increases battery lifespan by 15% (t(28) = 2.10, p = .045).
Methods
We tested 30 cells in a climate chamber.
Results
Humidity reduces electrolyte stability significantly (t(28) = 1.20, p = .03). Ion migration causes interface degradation.
Encapsulation reduces moisture damage.
(a+b)^2 = a^2 + 2*a*b + b^2
Limitations
We did not test other chemistries.
References
[1] Smith et al. Coatings. doi:10.1000/xyz123.
"""


def make_pdf(text: str = DOC_TEXT) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), text, fontsize=9)
    return doc.tobytes()


def inv(text: str) -> dict:
    d = {}
    for i, w in enumerate(text.split()):
        d.setdefault(w, []).append(i)
    return d


def openalex_json(papers):
    return {"results": [{
        "id": f"https://openalex.org/W{i}", "display_name": p["title"], "abstract_inverted_index": inv(p["abstract"]),
        "doi": f"https://doi.org/{p['doi']}", "publication_year": 2023,
        "authorships": [{"author": {"display_name": p["author"]}}], "primary_location": {"source": {"display_name": "J. Test"}},
        "best_oa_location": {"license": "cc-by", "pdf_url": ""}, "is_retracted": p.get("retracted", False),
        "cited_by_count": 3, "type": "article"} for i, p in enumerate(papers)]}


EXTERNAL = [
    {"title": "Graphene coating and battery lifespan: a randomized benchmark", "doi": "10.1/a", "author": "Ana Lopez",
     "abstract": "We found that graphene coating increases battery lifespan in a randomized benchmark of cells."},
    {"title": "Graphene coating hurts battery lifespan", "doi": "10.1/b", "author": "Bo Chen",
     "abstract": "We found that graphene coating decreases battery lifespan in small tests of coating cells."},
    {"title": "Energy retention in cells", "doi": "10.1/c", "author": "Cy Dahl",
     "abstract": "Battery lifespan improves energy retention markedly in all tested cells."},
]


def mock_connectors(papers=EXTERNAL, status=200, settings=None):
    settings = settings or Settings(offline=False, ads_token="")

    def handler(req: httpx.Request):
        if status != 200:
            return httpx.Response(status)
        host = req.url.host
        if "openalex" in host:
            return httpx.Response(200, json=openalex_json(papers))
        if "crossref" in host:
            return httpx.Response(200, json={"message": {"items": []}})
        if "arxiv" in host:
            return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        if "ebi.ac.uk" in host:
            return httpx.Response(200, json={"resultList": {"result": []}})
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    conns = {}
    for cls in (OpenAlexConnector, CrossrefConnector, ArxivConnector, EuropePMCConnector, NasaAdsConnector):
        c = cls(settings, client=client, sleep=lambda s: None)
        c.min_interval = 0
        conns[c.name] = c
    return conns


@pytest.fixture
def env(tmp_path):
    settings = Settings(database_url="sqlite://", data_dir=str(tmp_path / "data"), offline=False, api_key=TEST_KEY)
    sf = make_session_factory(make_engine("sqlite://"))
    store = LocalBlobStore(settings.data_dir)
    return settings, sf, store


@pytest.fixture
def client(env):
    settings, sf, store = env
    app = create_app(settings, sf, store, connectors=mock_connectors())
    return authenticated_client(app)


def authenticated_client(app):
    return TestClient(app, headers={"X-API-Key": TEST_KEY})
