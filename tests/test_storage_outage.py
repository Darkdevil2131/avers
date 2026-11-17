from contextlib import contextmanager
import sqlite3

import pytest

from ares.database import StorageUnavailable
from test_research import client, project, run


def test_runtime_storage_outage_returns_retryable_json_and_restores_access(tmp_path):
    state = tmp_path / 'state'
    api = client(state)
    pid = project(api)
    detached = tmp_path / 'detached'
    state.rename(detached)
    try:
        response = api.get('/projects')
        assert response.status_code == 503
        assert response.headers['Retry-After'] == '5'
        assert response.json() == {'detail': 'Research storage is temporarily unavailable. Please retry shortly.'}
        assert api.get('/health').status_code == 503
        assert api.get('/projects', headers={'Authorization': ''}).status_code == 401
    finally:
        detached.rename(state)
    assert api.get('/projects').raise_for_status().json()[0]['id'] == pid


def test_stream_discloses_outage_after_preflight_without_ending_run(tmp_path, monkeypatch):
    api = client(tmp_path, auto=False)
    pid = project(api)
    rid = run(api, pid)
    database = api.app.state.storage
    original = database.connect
    preflight = True

    @contextmanager
    def disconnect_after_preflight():
        nonlocal preflight
        if not preflight:
            raise StorageUnavailable()
        preflight = False
        with original() as db:
            yield db

    with monkeypatch.context() as patch:
        patch.setattr(database, 'connect', disconnect_after_preflight)
        stream = api.get(f'/projects/{pid}/runs/{rid}/stream').raise_for_status()
        assert 'event: unavailable' in stream.text
        assert 'Research storage is temporarily unavailable' in stream.text
        assert 'event: done' not in stream.text
    assert api.get(f'/projects/{pid}/runs/{rid}').json()['status'] == 'queued'


def test_sql_programming_error_is_not_an_availability_error(tmp_path):
    database = client(tmp_path).app.state.storage
    with pytest.raises(sqlite3.OperationalError, match='no such table'):
        with database.connect() as db:
            db.execute('SELECT * FROM nonexistent_test_table')


def test_pg_connection_errors_are_classified_without_a_database(monkeypatch):
    psycopg = pytest.importorskip('psycopg')
    from ares.postgres import PostgresDatabase

    database = object.__new__(PostgresDatabase)
    database.dsn = 'postgresql://localhost/test'
    for error in (psycopg.OperationalError('connection refused'), psycopg.errors.AdminShutdown('testing')):
        def fail(*args, **kwargs):
            raise error
        monkeypatch.setattr(psycopg, 'connect', fail)
        with pytest.raises(StorageUnavailable):
            with database.connect():
                pass
