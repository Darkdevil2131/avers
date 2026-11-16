import json
import subprocess
from types import SimpleNamespace
import pytest
from ares import local_reasoner as reasoner


@pytest.mark.parametrize('content,finish,expected', [
    ('{"answer":"unfinished', 'length', 'output_budget_exhausted'),
    ('{}', 'length', 'output_budget_exhausted'),
    ('{"answer":"unfinished', 'stop', 'invalid_json'),
    (None, 'stop', 'invalid_json'),
])
def test_incomplete_generation_is_not_repaired_or_accepted(content,finish,expected):
    result={'choices':[{'finish_reason':finish,'message':{'content':content}}]}
    assert reasoner.completion_payload(result)=={'error':expected}


def test_budget_failure_is_disclosed_without_generated_text(tmp_path,monkeypatch):
    model=tmp_path/'fixture.gguf';model.write_text('Never loaded')
    monkeypatch.setenv('ARES_REASONER_MODEL',str(model))
    monkeypatch.setattr(reasoner.subprocess,'run',lambda *a,**k:SimpleNamespace(
        returncode=0,stdout=json.dumps({'error':'output_budget_exhausted'})))
    result=reasoner.suggest('Question',[{'label':'S1','source_id':'s','quote':'A source observation with enough text.'}])
    assert result['status']=='rejected' and result['proposals']==[]
    assert 'output budget' in result['reason']


def test_timeout_reason_omits_model_and_executable_paths(tmp_path, monkeypatch):
    model = tmp_path/'private-model.gguf'
    model.touch()
    monkeypatch.setenv('ARES_REASONER_MODEL', str(model))

    def time_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs['timeout'])

    monkeypatch.setattr(reasoner.subprocess, 'run', time_out)
    result = reasoner.suggest('Question', [{'label': 'S1', 'source_id': 's', 'quote': 'A substantive observation.'}],
                              timeout_seconds=3)
    assert result == {'status': 'rejected', 'reason': 'Local inference exceeded its time budget', 'proposals': []}
