import pytest

from noesis.api.main import create_app
from noesis.config import Settings
from noesis.llm.client import LLMClient
from noesis.storage import get_store


@pytest.mark.parametrize("mode", ["api_key", "none", "unknown"])
def test_invalid_auth_fails_before_database_creation(tmp_path, mode):
    path = tmp_path / "noesis.db"
    with pytest.raises(RuntimeError, match="NOESIS_(API_KEY|AUTH_MODE)"):
        create_app(Settings(_env_file=None, auth_mode=mode, api_key="", database_url=f"sqlite:///{path}"))
    assert not path.exists()


def test_offline_defaults_and_no_automatic_paid_integrations():
    settings = Settings(_env_file=None)
    assert settings.offline
    assert not LLMClient(Settings(offline=False, llm_api_key="fixture")).available()
    with pytest.raises(ValueError, match="Only workspace storage"):
        get_store(Settings(storage_backend="s3"))


def test_retraction_swap_invalidates_index_without_count_change(env):
    from sqlalchemy import select

    from noesis.connectors.base import Paper
    from noesis.corpus.index import CorpusIndex
    from noesis.corpus.store import upsert
    from noesis.models import CorpusPaper

    _, factory, _ = env
    with factory.begin() as session:
        upsert(session, [
            Paper(source="fixture", title="Graphene coating longevity", doi="10.1/graphene", retracted=False),
            Paper(source="fixture", title="Perovskite moisture degradation", doi="10.1/perovskite", retracted=True),
        ], "technology", "test")
    with factory.begin() as session:
        index = CorpusIndex(session)
        assert index.search("graphene coating")
        for paper in session.scalars(select(CorpusPaper)):
            paper.retracted = not paper.retracted
    with factory.begin() as session:
        index = CorpusIndex(session)
        assert index.search("graphene coating") == []
        assert index.search("perovskite moisture")


def test_document_analysis_preserves_hypotheses_from_prior_runs(client, env):
    from sqlalchemy import select

    from noesis.models import Hypothesis, Job
    from tests.test_api_e2e import _run

    pid, document, first = _run(client)
    _, factory, _ = env
    with factory() as session:
        initial = set(session.scalars(select(Hypothesis.id).where(Hypothesis.job_id == first["id"])))
        assert initial
    res = client.post(f"/api/v1/projects/{pid}/documents/{document['id']}/analyze")
    assert res.status_code == 202
    with factory() as session:
        assert session.get(Job, res.json()["job_id"]).status == "completed"
        assert initial <= set(session.scalars(select(Hypothesis.id)))
