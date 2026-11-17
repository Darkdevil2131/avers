import threading
import time

import pytest

from ares.providers import ProviderError
from ares.replay import replay_markdown, verify_findings
from ares.retrieval import DENSE
from test_research import client, project, run


@pytest.fixture(autouse=True)
def use_lexical_fallback(monkeypatch):
    def unavailable(*args):
        raise OSError('Synthetic corpus test uses the lexical fallback')
    monkeypatch.setattr(DENSE, 'load', unavailable)
    monkeypatch.setattr(DENSE, 'rerank', unavailable)


def add(api, pid, label, text, study_id=None):
    return api.post(f'/projects/{pid}/sources', json={
        'title': label, 'url': f'https://example.org/{label}', 'study_id': study_id or label,
        'text': text, 'license_status': 'synthetic fixture',
    }).raise_for_status().json()


def test_report_preserves_opposing_observations_from_different_studies(tmp_path, monkeypatch):
    from ares import research

    def one_quote(question, citations, **options):
        return {'status': 'completed', 'answer': 'Single model-selected extract.', 'proposals': []}
    monkeypatch.setattr(research, 'suggest', one_quote)

    api = client(tmp_path)
    pid = project(api)
    dense_source = ' '.join(
        f'Humidity increased coating stability by {index}% in the coating stability trial.'
        for index in range(140)
    )
    first = add(api, pid, 'large-paper', dense_source, '10.5555/example')
    add(api, pid, 'duplicate-report', dense_source, 'https://doi.org/10.5555/Example')
    other = add(api, pid, 'opposing-paper', 'Humidity decreased coating stability by 12% in the coating stability trial.')
    rid = run(api, pid)
    route = f'/projects/{pid}/runs/{rid}'
    report = api.get(route + '/report').raise_for_status().json()
    comparison = report['evidence_comparison']
    assert comparison['status'] == 'multiple_source_candidates'
    assert len(comparison['observations']) == 2
    assert {item['study_identifier'] for item in comparison['observations']} == {'10.5555/example', 'opposing-paper'}
    assert len(report['citations']) <= 8
    by_id = {item['id']: item['text'] for item in api.get(f'/projects/{pid}/sources').json()}
    for item in comparison['observations']:
        assert by_id[item['source_id']][item['start_offset']:item['end_offset']] == item['quote']
    assert other['id'] in {item['source_id'] for item in comparison['observations']}
    assert first['id'] != other['id']
    assert 'Single model-selected extract.' not in report['summary']
    assert report['assessment'] == 'inconclusive'
    assert report['critique']['potential_disagreements']
    assert '## Evidence across sources' in report['markdown']
    bundle = api.get(route + '/replay.json').raise_for_status().json()
    assert replay_markdown(bundle) == report['markdown']
    assert verify_findings(bundle)['match']
    bundle['report']['evidence_comparison']['observations'][0]['quote'] = 'Changed quote.'
    with pytest.raises(ValueError, match='comparison'):
        replay_markdown(bundle)


def test_exact_copies_do_not_turn_one_observation_into_corroboration(tmp_path):
    api = client(tmp_path)
    pid = project(api)
    text = 'Humidity reduced coating stability during the synthetic experiment.'
    add(api, pid, 'original', text)
    add(api, pid, 'different-url-and-id', text)
    rid = run(api, pid)
    report = api.get(f'/projects/{pid}/runs/{rid}/report').raise_for_status().json()
    assert report['evidence_comparison']['status'] == 'single_source_candidate'
    assert report['evidence_comparison']['study_identifiers'] == 1
    assert 'Corroborating evidence is still needed' in report['summary']


def test_remote_discovery_overlaps_database_retrieval_and_failure_preserves_local_evidence(tmp_path, monkeypatch):
    from ares import research
    original = research.hybrid_search
    local_started = threading.Event()
    remote_started = threading.Event()

    class Provider:
        def search(self, query):
            remote_started.set()
            assert local_started.wait(3), 'Project search did not start while remote request was active'
            time.sleep(.04)
            raise ProviderError('Synthetic provider outage')

    def search(*args, **kwargs):
        local_started.set()
        assert remote_started.wait(3), 'Remote lookup did not start while project search was active'
        time.sleep(.04)
        return original(*args, **kwargs)

    monkeypatch.setattr(research, 'hybrid_search', search)
    api = client(tmp_path, provider=Provider())
    pid = project(api)
    add(api, pid, 'local', 'Humidity reduced coating stability during the synthetic experiment.')
    rid = run(api, pid, external=True)
    route = f'/projects/{pid}/runs/{rid}'
    report = api.get(route + '/report').raise_for_status().json()
    assert report['collection']['status'] == 'unavailable'
    assert report['evidence_comparison']['status'] == 'single_source_candidate'
    timing = report['execution']['parallel_work']
    assert 0 < timing['overlap_ms'] <= min(timing['project_evidence_ms'], timing['literature_discovery_ms'])
    events = api.get(route + '/events').json()
    assert next(item['payload'] for item in events if item['stage'] == 'research_branches_joined') == timing
