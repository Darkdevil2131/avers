"""Synthetic workflow tests with a mocked model; not scientific validation."""
import pytest
import ares.research as research
from test_research import client, project, source, run

QUOTE = 'Coating stability decreased after high humidity exposure in the controlled test.'


def candidate(text):
    return {'kind': 'model_generated_candidate', 'statement': text,
            'basis_quote': QUOTE, 'citation': 'S1', 'source_id': 'fixture',
            'mechanism': 'Requires investigation', 'falsification': 'A controlled test',
            'status': 'proposal_needs_review'}


@pytest.mark.parametrize('retry_outcome,expected_rejected,expected_kind', [
    ('corrected', 1, 'model_generated_candidate'),
    ('repeated', 2, 'replication_candidate'),
    ('failed', 1, 'replication_candidate'),
])
def test_opposition_gets_one_checked_retry_and_retains_rejections(tmp_path, monkeypatch, retry_outcome, expected_rejected, expected_kind):
    calls = []
    def fake_suggest(question, citations, **options):
        calls.append(options)
        if len(calls) == 1 or retry_outcome == 'repeated':
            return {'status': 'completed', 'proposals': [candidate('Coating stability increased after high humidity exposure.')]}
        if retry_outcome == 'failed':
            return {'status': 'rejected', 'reason': 'Synthetic model failure', 'proposals': []}
        return {'status': 'completed', 'proposals': [candidate('Coating stability decreased after high humidity exposure.')]}
    monkeypatch.setattr(research, 'suggest', fake_suggest)
    api = client(tmp_path)
    pid = project(api)
    source(api, pid, QUOTE)
    report = api.get(f'/projects/{pid}/runs/{run(api, pid)}/report').json()
    assert len(calls) == 2 and calls[0] == {}
    assert calls[1]['retry_opposition'] is True and 1 <= calls[1]['timeout_seconds'] <= 30
    assert len(report['critique']['rejected_proposals']) == expected_rejected
    assert report['reasoner']['initial_attempt']['status'] == 'completed'
    assert report['reasoner']['retry']['attempts'] == 1
    assert report['reasoner']['retry']['scientific_validity'] == 'unvalidated'
    assert report['hypotheses'][0]['kind'] == expected_kind
    assert report['assessment'] == 'inconclusive'
    assert 'One model correction attempt' in api.get(f"/projects/{pid}/runs/{report['run_id']}/report.md").text


def test_accepted_first_candidate_is_not_retried(tmp_path, monkeypatch):
    calls = []
    def fake_suggest(question, citations, **options):
        calls.append(options)
        return {'status': 'completed', 'proposals': [candidate('Coating stability decreased after high humidity exposure.')]}
    monkeypatch.setattr(research, 'suggest', fake_suggest)
    api = client(tmp_path)
    pid = project(api)
    source(api, pid, QUOTE)
    report = api.get(f'/projects/{pid}/runs/{run(api, pid)}/report').json()
    assert calls == [{}]
    assert 'retry' not in report['reasoner']
