import json

import pytest

from noesis import cli
from noesis.config import get_settings
from tests.test_ontology import OBO


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NOESIS_DATABASE_URL", f"sqlite:///{tmp_path}/cli.db")
    monkeypatch.setenv("NOESIS_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_cli_ontology_load_and_graph_dry_run_and_labelsheet(cli_env, capsys):
    obo = cli_env / "t.obo"
    obo.write_text(OBO)
    cli.main(["ontology", "--file", str(obo), "--name", "test"])
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"ontology": "test", "new": 3, "updated": 0}
    cli.main(["ontology", "--file", str(obo), "--name", "test"])                 # idempotent across runs (persisted to disk)
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["new"] == 0
    cli.main(["project-graph", "--project", "1", "--dry-run"])                   # empty project: only constraints, no crash
    out = capsys.readouterr().out
    assert "CREATE CONSTRAINT belief_id" in out and "MERGE" not in out
    sheet = cli_env / "sheet.jsonl"
    cli.main(["labelsheet", "--out", str(sheet), "-n", "5"])                     # empty corpus: writes nothing, says so
    res = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert res["written"] == 0 and res["candidates"] == 0


def test_network_graph_projection_refuses_clearly(cli_env):
    with pytest.raises(SystemExit, match="Neo4j network projection is disabled"):
        cli.main(["project-graph", "--project", "1"])
