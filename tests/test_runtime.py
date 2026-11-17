"""Readiness must reflect a worker connected to this API's database."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from ares.api import app_factory, create_app
from ares.database import Database
from ares.runtime import WorkerHeartbeat, record_heartbeat, runtime_status, STALE_SECONDS

TOKEN = 'x' * 40


def test_missing_wrong_stale_and_connected_worker(tmp_path, monkeypatch):
    monkeypatch.delenv('ARES_REASONER_MODEL', raising=False)
    app = create_app(tmp_path / 'api.db', {'fixture': TOKEN}, auto_process=False)
    api = TestClient(app, headers={'Authorization': 'Bearer ' + TOKEN})
    assert api.get('/health').status_code == 200
    assert api.get('/ready').status_code == 503
    assert api.get('/runtime', headers={'Authorization': ''}).status_code == 401
    assert api.get('/session').json()['mode'] == 'worker-managed'
    assert api.get('/runtime').json()['worker'] == 'missing'
    record_heartbeat(Database(tmp_path / 'wrong.db'), 'wrong-database')
    assert api.get('/ready').status_code == 503
    record_heartbeat(app.state.storage, 'same-database')
    assert api.get('/ready').json() == {'status': 'ready'}
    assert api.get('/runtime').json() == {
        'database': 'connected', 'queue_mode': 'db', 'worker': 'connected',
        'ready': True, 'active_workers': 1, 'reasoning': ['not_configured'],
    }
    with app.state.storage.connect() as db:
        db.execute('UPDATE worker_status SET last_seen=?', (time.time() - STALE_SECONDS - 1,))
    assert api.get('/runtime').json()['worker'] == 'stale'
    assert api.get('/ready').status_code == 503
    assert api.get('/health').status_code == 200


def test_heartbeat_updates_and_removes_its_record(tmp_path, monkeypatch):
    monkeypatch.setattr('ares.runtime.HEARTBEAT_SECONDS', .01)
    db = Database(tmp_path / 'heartbeat.db')
    with WorkerHeartbeat(db):
        with db.connect() as conn:
            first = conn.execute('SELECT last_seen FROM worker_status').fetchone()[0]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with db.connect() as conn:
                last = conn.execute('SELECT last_seen FROM worker_status').fetchone()[0]
            if last > first:
                break
            time.sleep(.01)
        assert last > first
        assert runtime_status(db, False)['ready'] is True
    assert runtime_status(db, False)['worker'] == 'missing'


def test_inline_readiness_and_private_database_error(tmp_path, monkeypatch):
    from contextlib import contextmanager
    app = create_app(tmp_path / 'inline.db', {'fixture': TOKEN})
    api = TestClient(app, headers={'Authorization': 'Bearer ' + TOKEN})
    assert api.get('/ready').status_code == 200
    assert api.get('/runtime').json()['worker'] == 'in_process'

    @contextmanager
    def broken():
        raise OSError('postgresql://private:secret@example.invalid/db')
        yield
    monkeypatch.setattr(app.state.storage, 'connect', broken)
    assert api.get('/ready').json() == {'status': 'unavailable'}
    assert api.get('/ready').status_code == 503
    assert api.get('/runtime').json() == {'database': 'unavailable', 'worker': 'unknown', 'ready': False}


def clear_config(monkeypatch):
    for name in ('ARES_DATABASE', 'ARES_APP_DATABASE', 'ARES_WORKER_DATABASE', 'ARES_QUEUE_MODE', 'DATABASE_URL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('ARES_CREDENTIALS', json.dumps({'fixture': TOKEN}))


def test_host_configuration_cannot_silently_select_another_database(tmp_path, monkeypatch):
    clear_config(monkeypatch)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://administrator@host/database')
    with pytest.raises(ValueError, match='restricted application DSN'):
        app_factory()
    monkeypatch.delenv('DATABASE_URL')
    monkeypatch.setenv('ARES_QUEUE_MODE', 'db')
    with pytest.raises(ValueError, match='Queued mode requires'):
        app_factory()
    monkeypatch.setenv('ARES_APP_DATABASE', str(tmp_path / 'application.db'))
    assert app_factory().state.storage.path == tmp_path / 'application.db'
    monkeypatch.setenv('ARES_QUEUE_MODE', 'typo')
    with pytest.raises(ValueError, match='inline or db'):
        app_factory()


def test_worker_requires_explicit_database(monkeypatch):
    from ares.cli import main
    clear_config(monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['ares', 'worker'])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


@pytest.mark.parametrize('port', ['invalid', '0', '65536'])
def test_server_rejects_invalid_port(monkeypatch, port):
    from ares.cli import main
    monkeypatch.setenv('PORT', port)
    monkeypatch.setattr(sys, 'argv', ['ares', 'serve'])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2


def test_real_http_api_and_separate_worker_database_routing(tmp_path):
    """Real subprocesses and HTTP; synthetic evidence, no external collection or model."""
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith('ARES_') and k != 'DATABASE_URL'}
    env.update(ARES_CREDENTIALS=json.dumps({'fixture': TOKEN, 'outsider': 'o' * 40}),
               ARES_QUEUE_MODE='db', ARES_DATABASE=str(tmp_path / 'shared.db'), PORT=str(port),
               ARES_MODEL_CACHE=str(tmp_path / 'empty-model-cache'), HF_HUB_OFFLINE='1')
    processes = []
    logs = []

    def start(command, settings):
        log = open(tmp_path / f'process-{len(processes)}.log', 'w')
        logs.append(log)
        proc = subprocess.Popen([sys.executable, '-m', 'ares.cli', command], cwd=root,
                                env=settings, stdout=log, stderr=subprocess.STDOUT)
        processes.append(proc)
        return proc

    def stop(proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def until(check, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if check():
                    return
            except httpx.ConnectError:
                pass
            time.sleep(.1)
        pytest.fail('Process integration deadline exceeded; inspect process logs in ' + str(tmp_path))

    try:
        # The API's model setting must not be mistaken for the worker's configuration.
        server = start('serve', dict(env, ARES_REASONER_MODEL=str(tmp_path / 'api-only-missing.gguf')))
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=15,
                          headers={'Authorization': 'Bearer ' + TOKEN}) as api:
            until(lambda: api.get('/health').status_code == 200)
            assert server.poll() is None
            assert api.get('/ready').status_code == 503
            pid = api.post('/projects', json={'name': 'Runtime connection test'}).json()['id']
            text = 'Humidity reduced coating stability by 20% in a synthetic routing test. This is not scientific evidence.'
            source = api.post(f'/projects/{pid}/sources', json={
                'url': 'https://example.org/runtime-fixture', 'text': text, 'license_status': 'synthetic fixture',
            }).json()
            passages = api.get(f'/projects/{pid}/retrieve', params={'q': 'humidity coating stability'}).json()['passages']
            assert passages and passages[0]['source_id'] == source['id']
            assert api.get(f'/projects/{pid}/retrieve', params={'q': 'humidity coating stability'},
                           headers={'Authorization': 'Bearer ' + 'o' * 40}).status_code == 404
            rid = api.post(f'/projects/{pid}/runs', json={
                'question': 'How does humidity affect coating stability?', 'external': False,
            }).json()['id']
            route = f'/projects/{pid}/runs/{rid}'
            wrong_db = Database(tmp_path / 'wrong-worker.db')
            wrong = start('worker', dict(env, ARES_WORKER_DATABASE=str(wrong_db.path)))
            until(lambda: runtime_status(wrong_db, False)['ready'])
            assert api.get('/runtime').json()['worker'] == 'missing'
            assert api.get('/ready').status_code == 503
            assert api.get(route).json()['status'] == 'queued'
            stop(wrong)
            worker = start('worker', env)
            until(lambda: api.get('/ready').status_code == 200)
            assert api.get('/runtime').json()['worker'] == 'connected'
            assert api.get('/runtime').json()['reasoning'] == ['not_configured']
            until(lambda: api.get(route).json()['status'] in {'completed', 'failed'})
            assert api.get(route).json()['status'] == 'completed'
            report = api.get(route + '/report').json()
            assert report['citations'] and report['reasoner']['status'] == 'unavailable'
            for cite in report['citations']:
                assert cite['source_id'] == source['id']
                assert cite['quote'] == text[cite['start_offset']:cite['end_offset']]
            stages = {row['stage'] for row in api.get(route + '/events').json()}
            assert {'queued', 'plan', 'memory_retrieval', 'audit', 'report'} <= stages
            assert api.get(f'/projects/{pid}/memory').json()[0]['status'] == 'pending'
            stop(worker)
            until(lambda: api.get('/ready').status_code == 503)
            assert api.get('/health').status_code == 200
            assert api.get(route + '/report').json()['citations'] == report['citations']
    finally:
        for proc in processes:
            stop(proc)
        for log in logs:
            log.close()
