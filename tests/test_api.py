import sqlite3

import pytest
from fastapi.testclient import TestClient

from ares.api import create_app


@pytest.fixture
def workspace(tmp_path):
    path = tmp_path / "ares.db"
    app = create_app(path, {"alice": "a" * 40, "bob": "b" * 40})
    return path, TestClient(app, headers={"Authorization": "Bearer " + "a" * 40}), TestClient(
        app, headers={"Authorization": "Bearer " + "b" * 40}
    )


def test_startup_fails_without_credentials(tmp_path):
    with pytest.raises(ValueError):
        create_app(tmp_path / "db", {})
    assert not (tmp_path / "db").exists()


def test_authentication_and_project_isolation(workspace):
    _, alice, bob = workspace
    assert TestClient(alice.app).get("/projects").status_code == 401
    pid = alice.post("/projects", json={"name": "Materials"}).json()["id"]
    assert bob.get("/projects").json() == []
    assert bob.get(f"/projects/{pid}/sources").status_code == 404
    assert bob.post(f"/projects/{pid}/runs", json={"question": "Does coating improve stability?"}).status_code == 404


def test_provenance_deduplication_and_immutability(workspace):
    path, alice, _ = workspace
    pid = alice.post("/projects", json={"name": "Materials"}).json()["id"]
    source = {"url": "https://example.org/paper", "text": "A synthetic test passage.", "license_status": "fixture"}
    first = alice.post(f"/projects/{pid}/sources", json=source).json()
    assert first["id"] == alice.post(f"/projects/{pid}/sources", json=source).json()["id"]
    assert first["verification"] == "unverified"
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE sources SET text='tampered'")
    assert alice.get(f"/projects/{pid}/sources").json()[0]["text"] == source["text"]


def test_runs_survive_restart_and_stay_project_scoped(workspace):
    path, alice, _ = workspace
    pid = alice.post("/projects", json={"name": "A"}).json()["id"]
    other = alice.post("/projects", json={"name": "B"}).json()["id"]
    run = alice.post(f"/projects/{pid}/runs", json={"question": "Does a coating resist humidity?"}).json()
    fresh = TestClient(create_app(path, {"alice": "a" * 40}), headers=alice.headers)
    assert fresh.get(f"/projects/{pid}/runs/{run['id']}").status_code == 200
    assert fresh.get(f"/projects/{other}/runs/{run['id']}").status_code == 404
    with sqlite3.connect(path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM runs")
