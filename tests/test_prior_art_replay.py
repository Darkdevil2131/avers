import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from ares.replay import replay_markdown, verify_findings
from ares.providers import ProviderError
from test_research import KEYS, client, project, run, source


class Literature:
    def __init__(self, outcome='available'):
        self.queries = []
        self.outcome = outcome

    def search(self, query):
        self.queries.append(query)
        if len(self.queries) > 1:
            if self.outcome == 'unavailable':
                raise ProviderError('Offline test provider')
            if self.outcome == 'identifiers_only':
                return [{'origin': 'ncbi_metadata', 'title': 'Open-access candidate PMC5'}]
            return [{'title': 'Humidity and coating stability in a replication study',
                     'url': 'https://example.org/replication', 'study_id': 'doi:10.5555/replication'}]
        return [
            {'title': 'Humidity and coating stability across substrates',
             'url': 'https://example.org/related', 'text': 'Humidity and coating stability',
             'study_id': 'doi:10.5555/fixture', 'license_status': 'fixture',
             'origin': 'fixture_metadata'},
            {'title': 'Humidity and coating stability across substrates',
             'url': 'https://example.org/duplicate', 'text': 'Humidity and coating stability',
             'study_id': 'https://doi.org/10.5555/FIXTURE', 'license_status': 'fixture',
             'origin': 'fixture_metadata'},
        ]


def test_report_screens_literature_and_replays_saved_artifact(tmp_path, monkeypatch):
    monkeypatch.delenv('ARES_REASONER_MODEL', raising=False)
    provider = Literature()
    api = client(tmp_path, provider=provider)
    pid = project(api)
    original = source(api, pid, 'Humidity reduced the stability of the coating during the confidential zircon test.')
    rid = run(api, pid, external=True)
    route = f'/projects/{pid}/runs/{rid}/report'
    live = api.get(route).json()
    candidate, = live['hypotheses']
    screen = candidate['prior_art']
    assert screen['status'] == 'possible_overlap'
    assert not screen['novelty_verified']
    assert [match['title'] for match in screen['matches']] == [
        'Humidity and coating stability across substrates', 'Humidity and coating stability in a replication study']
    assert screen['topic_search'] == {'status': 'completed', 'query': '"humidity" AND "coating" AND "stability"', 'records': 1}
    assert provider.queries == ['How does humidity affect coating stability?', screen['topic_search']['query']]
    assert [entry['strategy'] for entry in live['collection']['queries']] == ['primary_evidence', 'prior_art']
    assert all(c['url'] != 'https://example.org/replication' for c in live['citations'])
    assert 'Literature title screen: possible overlap.' in live['markdown']
    assert 'Bibliographic titles returned: 1.' in live['markdown']

    archive = api.get(f'/projects/{pid}/runs/{rid}/replay.json')
    assert archive.status_code == 200
    assert 'attachment' in archive.headers['content-disposition']
    bundle = archive.json()
    assert replay_markdown(bundle) == live['markdown']
    assert bundle['report']['execution']['planner_policy'] == 'context-aware-follow-up-v2'
    archive_path, output_path = tmp_path/'bundle.json', tmp_path/'report.md'
    archive_path.write_bytes(archive.content)
    subprocess.run([sys.executable,'-m','ares.replay',str(archive_path),str(output_path)],
                   check=True, env={**os.environ, 'ARES_DATABASE':'state/must-not-be-used'})
    assert output_path.read_text() == live['markdown']

    outsider = TestClient(api.app, headers={'Authorization': 'Bearer ' + KEYS['bob']})
    assert outsider.get(f'/projects/{pid}/runs/{rid}/replay.json').status_code == 404
    altered = json.loads(archive.content)
    altered['sources'][original['id']]['text'] += ' changed'
    with pytest.raises(ValueError, match='hash'):
        replay_markdown(altered)
    altered = json.loads(archive.content)
    altered['report']['citations'][0]['quote'] = 'different excerpt'
    with pytest.raises(ValueError, match='quote'):
        replay_markdown(altered)
    altered = json.loads(archive.content)
    altered['report']['findings'][0]['statement'] = 'Invented finding text'
    with pytest.raises(ValueError, match='finding does not match'):
        replay_markdown(altered)

    api.post(f'/projects/{pid}/sources/{original["id"]}/review', json={
        'status':'retracted','reason':'Synthetic test retraction',
    }).raise_for_status()
    assert api.get(route).json()['markdown'].startswith('> WARNING:')
    assert api.get(f'/projects/{pid}/runs/{rid}/replay.json').json() == bundle


def test_replay_can_compare_extraction_and_exposes_changes(tmp_path, monkeypatch):
    from ares.retrieval import DENSE

    monkeypatch.delenv('ARES_REASONER_MODEL', raising=False)
    monkeypatch.setattr(DENSE, 'rerank', lambda question, values: [1.0] * len(values))
    monkeypatch.setattr(DENSE, 'reranker_artifact_hash', None)
    api = client(tmp_path)
    pid = project(api)
    source(api, pid)
    rid = run(api, pid)
    bundle = api.get(f'/projects/{pid}/runs/{rid}/replay.json').json()
    result = verify_findings(bundle)
    assert result['match'] and result['saved_count'] > 0
    assert result['model_identity_verified'] is False

    monkeypatch.setattr(DENSE, 'rerank', lambda question, values: (_ for _ in ()).throw(RuntimeError('offline')))
    result = verify_findings(bundle)
    assert result['match'] is False
    assert result['saved'][0]['method'] != result['rerun'][0]['method']


def test_replay_checks_recorded_reranker_identity(tmp_path, monkeypatch):
    from ares.retrieval import DENSE

    monkeypatch.delenv('ARES_REASONER_MODEL', raising=False)
    monkeypatch.setattr(DENSE, 'rerank', lambda question, values: [1.0] * len(values))
    monkeypatch.setattr(DENSE, 'reranker_artifact_hash', 'a' * 64)
    api = client(tmp_path)
    pid = project(api)
    source(api, pid)
    rid = run(api, pid)
    bundle = api.get(f'/projects/{pid}/runs/{rid}/replay.json').json()
    assert verify_findings(bundle)['model_identity_verified'] is True
    monkeypatch.setattr(DENSE, 'reranker_artifact_hash', 'b' * 64)
    result = verify_findings(bundle)
    assert result['model_identity_verified'] is False
    assert result['match'] is False
    assert result['saved'] == result['rerun']
    monkeypatch.setattr(DENSE, 'reranker_artifact_hash', None)
    assert verify_findings(bundle)['match'] is False


def test_model_snapshot_digest_includes_paths_and_bytes(tmp_path):
    from ares.retrieval import artifact_digest

    (tmp_path / 'model.onnx').write_bytes(b'fixture weights')
    (tmp_path / 'tokenizer.json').write_text('fixture tokenizer')
    first = artifact_digest(tmp_path)
    assert artifact_digest(tmp_path) == first
    (tmp_path / 'tokenizer.json').write_text('changed tokenizer')
    assert artifact_digest(tmp_path) != first


@pytest.mark.parametrize('outcome,status', [('unavailable', 'unavailable'), ('identifiers_only', 'titles_unavailable')])
def test_topic_search_reports_missing_titles(tmp_path, monkeypatch, outcome, status):
    monkeypatch.delenv('ARES_REASONER_MODEL', raising=False)
    api = client(tmp_path, provider=Literature(outcome))
    pid = project(api)
    source(api, pid)
    rid = run(api, pid, external=True)
    report = api.get(f'/projects/{pid}/runs/{rid}/report').json()
    screen = report['hypotheses'][0]['prior_art']
    assert screen['topic_search']['status'] == status
    assert screen['topic_search']['records'] == 0
    assert screen['status'] == 'possible_overlap'  # Keep first-search matches.


def test_local_screen_does_not_contact_literature_provider(tmp_path, monkeypatch):
    monkeypatch.delenv('ARES_REASONER_MODEL', raising=False)
    provider = Literature()
    api = client(tmp_path, provider=provider)
    pid = project(api)
    source(api, pid)
    rid = run(api, pid)
    report = api.get(f'/projects/{pid}/runs/{rid}/report').json()
    assert report['hypotheses'][0]['prior_art']['topic_search']['status'] == 'not_requested'
    assert provider.queries == []
