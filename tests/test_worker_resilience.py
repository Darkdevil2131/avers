import logging
import pytest
from fastapi.testclient import TestClient
from ares.api import create_app
from ares.cli import run_worker

class Stop:
    def __init__(self):self.done=False;self.delays=[]
    def is_set(self):return self.done
    def wait(self,delay):self.delays.append(delay)

def test_failed_job_does_not_prevent_next_report(tmp_path,monkeypatch,caplog):
    import ares.research as research
    app=create_app(tmp_path/'worker.db',{'alice':'a'*40},auto_process=False)
    c=TestClient(app,headers={'Authorization':'Bearer '+'a'*40})
    pid=c.post('/projects',json={'name':'Failure recovery'}).json()['id']
    c.post(f'/projects/{pid}/sources',json={'url':'https://example.org/fixture','text':'Humidity reduced coating stability by 20% in a synthetic test.','license_status':'fixture'})
    ids=[c.post(f'/projects/{pid}/runs',json={'question':q}).json()['id'] for q in ['First humidity question','Second humidity question']]
    actual=research.extract;calls=[]
    def fail_first(citations,question):
        calls.append(question)
        if len(calls)==1:raise RuntimeError('private source content must not appear in logs')
        return actual(citations,question)
    monkeypatch.setattr(research,'extract',fail_first)
    stop=Stop();engine=app.state.engine
    class Drain:
        def run_once(self):
            result=engine.run_once()
            if not result:stop.done=True
            return result
    with caplog.at_level(logging.ERROR):run_worker(Drain(),stop)
    states=[c.get(f'/projects/{pid}/runs/{rid}').json()['status'] for rid in ids]
    assert states==['failed','completed']
    assert c.get(f'/projects/{pid}/runs/{ids[1]}/report').json()['citations']
    assert 'private source content' not in caplog.text
    assert 'RuntimeError' in caplog.text
    assert stop.delays[0]==1

def test_repeated_infrastructure_errors_back_off_and_can_stop():
    stop=Stop();attempts=[]
    class Broken:
        def run_once(self):
            attempts.append(1)
            if len(attempts)==8:stop.done=True
            raise OSError('private connection URL')
    run_worker(Broken(),stop)
    assert stop.delays==[1,2,4,8,16,30,30,30]


def check_queue_admission(app):
    c=TestClient(app,headers={'Authorization':'Bearer '+'q'*40})
    pid=c.post('/projects',json={'name':'Bounded queue'}).json()['id']
    route=f'/projects/{pid}/runs';body={'question':'What does the evidence show about humidity?'}
    first=c.post(route,json=body,headers={'Idempotency-Key':'first'}).json()['id']
    for _ in range(18):assert c.post(route,json=body).status_code==201
    from concurrent.futures import ThreadPoolExecutor
    # Only one free slot: simultaneous unkeyed submissions must not overfill it.
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses=list(pool.map(lambda _:c.post(route,json=body).status_code,range(8)))
    assert statuses.count(201)==1 and statuses.count(429)==7
    assert len(c.get(route).json())==20
    duplicate=c.post(route,json=body,headers={'Idempotency-Key':'first'})
    assert duplicate.status_code==201 and duplicate.json()['id']==first
    rejected=c.post(route,json=body)
    assert rejected.status_code==429 and rejected.headers['Retry-After']=='10'
    assert c.post(route+'/'+first+'/cancel').status_code==200
    assert c.post(route,json=body).status_code==201
    other=c.post('/projects',json={'name':'Independent queue'}).json()['id']
    assert c.post(f'/projects/{other}/runs',json=body).status_code==201

def test_sqlite_concurrent_queue_limit_and_idempotency(tmp_path):
    check_queue_admission(create_app(tmp_path/'queue.db',{'queue':'q'*40},auto_process=False))


def check_lease_fencing(app, monkeypatch, outcome):
    import ares.research as research
    from ares.postgres import PRINCIPAL
    c = TestClient(app, headers={'Authorization': 'Bearer ' + 'f' * 40})
    pid = c.post('/projects', json={'name': 'Lease fencing'}).json()['id']
    rid = c.post(f'/projects/{pid}/runs', json={'question': 'What does the evidence actually show?'}).json()['id']
    dbs, engine = app.state.storage, app.state.engine
    calls = []
    def interleave(citations, question):
        calls.append(1)
        if len(calls) == 1:
            if outcome == 'cancel_then_error':
                with dbs.connect() as db:
                    db.execute("UPDATE run_state SET cancelled=1,status='cancelled' WHERE run_id=?", (rid,))
            else:
                with dbs.connect() as db:
                    db.execute('UPDATE run_state SET lease_until=0 WHERE run_id=?', (rid,))
                if outcome != 'expire_only':
                    assert engine.execute(rid) is True  # A replacement finishes before the old worker resumes.
            if outcome in {'replacement_then_error', 'cancel_then_error'}:
                raise RuntimeError('Old worker failed after losing ownership')
        return []
    monkeypatch.setattr(research, 'extract', interleave)
    token = PRINCIPAL.set('fence')
    try:
        if outcome in {'replacement_then_error', 'cancel_then_error'}:
            with pytest.raises(RuntimeError):
                engine.execute(rid)
        else:
            assert engine.execute(rid) is False
        with dbs.connect() as db:
            state = db.execute('SELECT * FROM run_state WHERE run_id=?', (rid,)).fetchone()
            reports = db.execute('SELECT count(*) FROM reports WHERE run_id=?', (rid,)).fetchone()[0]
            memory = db.execute('SELECT count(*) FROM research_memory WHERE run_id=?', (rid,)).fetchone()[0]
            failures = db.execute("SELECT count(*) FROM run_events WHERE run_id=? AND stage='failed'", (rid,)).fetchone()[0]
        expected = 'cancelled' if outcome == 'cancel_then_error' else 'running' if outcome == 'expire_only' else 'completed'
        assert state['status'] == expected and state['error'] is None
        assert reports == memory == (1 if expected == 'completed' else 0)
        assert failures == 0
    finally:
        PRINCIPAL.reset(token)


@pytest.mark.parametrize('outcome', ['replacement', 'replacement_then_error', 'cancel_then_error', 'expire_only'])
def test_stale_worker_cannot_publish_or_overwrite_status(tmp_path, monkeypatch, outcome):
    app = create_app(tmp_path / 'fencing.db', {'fence': 'f' * 40}, auto_process=False)
    check_lease_fencing(app, monkeypatch, outcome)
