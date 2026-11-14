import pytest
from test_research import client

@pytest.mark.parametrize('value,expected', [('A'*40,'a'*40),('', 'unknown'),('short','unknown'),('token-not-a-commit','unknown')])
def test_session_only_exposes_valid_revision(tmp_path,monkeypatch,value,expected):
    monkeypatch.setenv('ARES_BUILD_REVISION',value)
    c=client(tmp_path)
    assert c.get('/session').json()['build_revision']==expected
    assert c.get('/session',headers={'Authorization':'Bearer invalid'}).status_code==401
