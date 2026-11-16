"""Synthetic workflow tests with a mocked model; not scientific validation."""
from types import SimpleNamespace

import pytest
import ares.research as research
from ares.agents import proposal_critic
from test_research import client, project, source, run

QUOTE = 'Coating stability decreased after high humidity exposure in the controlled test.'


def candidate(text):
    return {'kind': 'model_generated_candidate', 'statement': text,
            'basis_quote': QUOTE, 'citation': 'S1', 'source_id': 'fixture',
            'mechanism': 'Requires investigation', 'falsification': 'A controlled test',
            'status': 'proposal_needs_review'}


@pytest.mark.parametrize('retry_outcome,expected_rejected,expected_kind', [
    ('corrected', 1, 'model_generated_candidate'),
    ('restated_relationship', 2, 'replication_candidate'),
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
        if retry_outcome == 'restated_relationship':
            proposal = candidate('Coating adhesion decreases when humidity increases.')
            proposal['falsification'] = 'Coating adhesion would increase when humidity decreases.'
            return {'status': 'completed', 'proposals': [proposal]}
        return {'status': 'completed', 'proposals': [candidate('Coating stability decreased after high humidity exposure.')]}
    monkeypatch.setattr(research, 'suggest', fake_suggest)
    api = client(tmp_path)
    pid = project(api)
    source(api, pid, QUOTE)
    report = api.get(f'/projects/{pid}/runs/{run(api, pid)}/report').json()
    assert len(calls) == 2 and calls[0] == {'timeout_seconds': 90}
    assert calls[1]['retry_opposition'] is True and 1 <= calls[1]['timeout_seconds'] <= 30
    assert len(report['critique']['rejected_proposals']) == expected_rejected
    assert report['reasoner']['initial_attempt']['status'] == 'completed'
    assert report['reasoner']['retry']['attempts'] == 1
    assert report['reasoner']['retry']['scientific_validity'] == 'unvalidated'
    assert report['hypotheses'][0]['kind'] == expected_kind
    assert report['assessment'] == 'inconclusive'
    markdown = api.get(f"/projects/{pid}/runs/{report['run_id']}/report.md").text
    assert 'One model correction attempt' in markdown
    if retry_outcome == 'restated_relationship':
        rejected = report['critique']['rejected_proposals'][-1]
        assert rejected['candidate']['falsification'] == 'Coating adhesion would increase when humidity decreases.'
        assert rejected['check']['falsification_check']['status'] == 'restates_directional_relationship'
        assert 'The proposed falsifier restates the hypothesis’s directional relationship' in markdown


@pytest.mark.parametrize('falsification,status', [
    ('Coating adhesion increases when humidity increases.', 'opposes_directional_relationship'),
    ('Coating adhesion decreases when humidity decreases.', 'opposes_directional_relationship'),
    ('Coating adhesion does not decrease when humidity increases.', 'requires_review'),
    ('Coating hardness increases when humidity decreases.', 'requires_review'),
    ('Coating adhesion increases when humidity decreases after heating.', 'requires_review'),
])
def test_simple_counterexample_and_unresolved_comparisons_are_not_rejected(falsification, status):
    proposal = candidate('Coating adhesion decreases when humidity increases.')
    proposal['falsification'] = falsification
    check = proposal_critic(proposal)
    assert check['falsification_check'] == {'status': status, 'context_verified': False}
    assert check['accepted_as_candidate']
    assert check['scientific_validation'] is False


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
    assert calls == [{'timeout_seconds': 90}]
    assert 'retry' not in report['reasoner']


@pytest.mark.parametrize('retrieval_seconds,expected_timeout', [(175, 4), (179.5, None)])
def test_first_inference_respects_time_left_after_retrieval(tmp_path, monkeypatch, retrieval_seconds, expected_timeout):
    elapsed = 0
    original_search = research.hybrid_search
    monkeypatch.setattr(research, 'time', SimpleNamespace(
        time=research.time.time, monotonic=lambda: elapsed,
    ))

    def slow_search(*args, **kwargs):
        nonlocal elapsed
        result = original_search(*args, **kwargs)
        elapsed = retrieval_seconds
        return result

    calls = []

    def timed_out(question, citations, **options):
        calls.append(options['timeout_seconds'])
        elapsed_at_timeout = retrieval_seconds + options['timeout_seconds']
        assert elapsed_at_timeout < 180
        return {'status': 'rejected', 'reason': 'Local inference exceeded its time budget', 'proposals': []}

    monkeypatch.setattr(research, 'hybrid_search', slow_search)
    monkeypatch.setattr(research, 'suggest', timed_out)
    api = client(tmp_path)
    pid = project(api)
    source(api, pid, QUOTE)
    report = api.get(f'/projects/{pid}/runs/{run(api, pid)}/report').json()
    assert calls == ([] if expected_timeout is None else [expected_timeout])
    assert report['reasoner']['status'] == ('cancelled_or_budget_exhausted' if expected_timeout is None else 'rejected')
    assert report['hypotheses'][0]['kind'] == 'replication_candidate'
    assert report['citations'][0]['quote'] == QUOTE
