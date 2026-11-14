import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from ares.replay import replay_markdown
from test_research import KEYS, client, project, run, source


class Literature:
    def search(self, query):
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
    api = client(tmp_path, provider=Literature())
    pid = project(api)
    original = source(api, pid)
    rid = run(api, pid, external=True)
    route = f'/projects/{pid}/runs/{rid}/report'
    live = api.get(route).json()
    candidate, = live['hypotheses']
    screen = candidate['prior_art']
    assert screen['status'] == 'possible_overlap'
    assert not screen['novelty_verified']
    assert [match['title'] for match in screen['matches']] == ['Humidity and coating stability across substrates']
    assert 'Literature title screen: possible overlap.' in live['markdown']

    archive = api.get(f'/projects/{pid}/runs/{rid}/replay.json')
    assert archive.status_code == 200
    assert 'attachment' in archive.headers['content-disposition']
    bundle = archive.json()
    assert replay_markdown(bundle) == live['markdown']
    assert bundle['report']['execution']['planner_policy'] == 'evidence-triggered-follow-up-v1'
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

    api.post(f'/projects/{pid}/sources/{original["id"]}/review', json={
        'status':'retracted','reason':'Synthetic test retraction',
    }).raise_for_status()
    assert api.get(route).json()['markdown'].startswith('> WARNING:')
    assert api.get(f'/projects/{pid}/runs/{rid}/replay.json').json() == bundle
