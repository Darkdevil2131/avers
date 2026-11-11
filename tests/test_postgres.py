"""Requires a disposable PostgreSQL service; never points to production data."""
import os
import pytest
from fastapi.testclient import TestClient

pytestmark=pytest.mark.skipif(not os.environ.get('ARES_TEST_POSTGRES'),reason='Disposable PostgreSQL service not configured')

def test_database_rls_and_research_end_to_end():
    from ares.api import create_app
    from ares.postgres import PRINCIPAL
    app=create_app(os.environ['ARES_TEST_POSTGRES'],{'alice':'a'*40,'bob':'b'*40})
    alice=TestClient(app,headers={'Authorization':'Bearer '+'a'*40})
    bob=TestClient(app,headers={'Authorization':'Bearer '+'b'*40})
    p=alice.post('/projects',json={'name':'Alice isolated research'}).json()['id']
    s=alice.post(f'/projects/{p}/sources',json={'url':'https://example.org/rls','text':'Humidity reduced coating stability in the synthetic database isolation test.','license_status':'synthetic fixture'}).json()
    assert s.get('id'),s
    assert bob.get(f'/projects/{p}/sources').status_code==404
    token=PRINCIPAL.set('bob')
    try:
        with app.state.storage.connect() as db:
            # Deliberately omit project scope: RLS must still protect Alice's source.
            assert not db.execute('SELECT * FROM sources WHERE id=?',(s['id'],)).fetchall()
            assert not db.execute('SELECT * FROM projects WHERE id=?',(p,)).fetchall()
        with pytest.raises(Exception):
            with app.state.storage.connect() as db:
                db.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?)',('forbidden',p,'x','x','x','x','x'))
    finally:PRINCIPAL.reset(token)
    r=alice.post(f'/projects/{p}/runs',json={'question':'How does humidity affect coating stability?'}).json()
    assert r.get('id'),r
    report=alice.get(f"/projects/{p}/runs/{r['id']}/report")
    assert report.status_code==200,report.text
    assert report.json()['citations']
    assert alice.put(f'/projects/{p}/members',json={'username':'bob','role':'viewer'}).status_code==200
    token=PRINCIPAL.set('bob')
    try:
        with app.state.storage.connect() as db:assert db.execute('SELECT id FROM sources WHERE id=?',(s['id'],)).fetchone()
        with pytest.raises(Exception):
            with app.state.storage.connect() as db:
                db.execute('INSERT INTO source_reviews(source_id,status,reason,actor,created_at) VALUES(?,?,?,?,?)',(s['id'],'active','unauthorized viewer write','bob','now'))
    finally:PRINCIPAL.reset(token)
    assert bob.post(f'/projects/{p}/runs',json={'question':'Can a viewer write a run?'}).status_code==404
    assert bob.get(f"/projects/{p}/runs/{r['id']}/report").status_code==200
    assert bob.get(f'/projects/{p}/audit').status_code==404
