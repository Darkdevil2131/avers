from fastapi.testclient import TestClient

from test_evidence import CONTEXT
from test_research import KEYS, client, project


def exercise_claim_run(api):
    project_id = project(api)
    prefix = f'/projects/{project_id}'
    claim = api.post(prefix + '/claims', json={
        'statement': 'Humidity affects coating stability.', 'fingerprint': CONTEXT,
    }).json()['id']
    foreign_project = project(api)
    foreign_claim = api.post(f'/projects/{foreign_project}/claims', json={
        'statement': 'This claim belongs to a separate project.', 'fingerprint': CONTEXT,
    }).json()['id']
    body = {'question': 'Does humidity affect coating stability?', 'claim_id': claim}
    assert api.post(prefix + '/runs', json={**body, 'claim_id': foreign_claim}).status_code == 404

    def link(text, stance, fingerprint=CONTEXT, study_id='DOI:10.5555/Coating-Fixture'):
        item = api.post(prefix + '/sources', json={
            'url': 'https://example.org/' + stance, 'title': stance,
            'text': text, 'license_status': 'Synthetic fixture', 'study_id': study_id,
        })
        assert item.status_code == 201
        source_id = item.json()['id']
        evidence = api.post(f'{prefix}/claims/{claim}/evidence', json={
            'source_id': source_id, 'start_offset': 0, 'end_offset': len(text),
            'stance': stance, 'fingerprint': fingerprint, 'rationale': 'Fixture researcher judgment',
        })
        assert evidence.status_code == 201
        return source_id

    def submit(key):
        response = api.post(prefix + '/runs', json=body, headers={'Idempotency-Key': key})
        assert response.status_code == 201
        return response.json()['id']

    support_text = 'Exact reviewer quote with Unicode: 23 °C and 80% RH. ' + 'sample ' * 300
    supported_source = link(support_text, 'supports')
    mismatched = link('Mismatch in the measurement context.', 'contradicts', {**CONTEXT, 'measurement': 'different method'})
    first = submit('reviewed-assessment')
    route = f'{prefix}/runs/{first}/report'
    response = api.get(route)
    assert response.status_code == 200
    report = response.json()
    assert report['assessment'] == 'supported'
    assert report['reviewed_claim']['calibrated'] is False
    assert report['reviewed_claim']['independence_verified'] is False
    details = {item['source_id']: item for item in report['reviewed_claim']['evidence']}
    assert details[supported_source]['quote'] == support_text[:2000]
    assert details[supported_source]['quote_truncated'] is True
    assert details[supported_source]['end_offset'] == len(support_text)
    assert details[supported_source]['exclusions'] == []
    assert details[mismatched]['exclusions'] == ['context-mismatched']
    assert report['review_links_changed'] is False
    assert submit('reviewed-assessment') == first
    conflict = api.post(prefix + '/runs', json={'question': body['question']},
                        headers={'Idempotency-Key': 'reviewed-assessment'})
    assert conflict.status_code == 409

    link('Second excerpt from the same article fixture.', 'contradicts',
         study_id='https://doi.org/10.5555/coating-fixture')
    assert api.get(route).json()['review_links_changed'] is True
    mixed = f"{prefix}/runs/{submit('mixed-assessment')}/report"
    mixed_report = api.get(mixed).json()
    assert mixed_report['assessment'] == 'mixed'
    assert mixed_report['reviewed_claim']['study_groups'] == [
        {'identifier': '10.5555/coating-fixture', 'stances': ['contradicts', 'supports']},
    ]
    retraction = api.post(f'{prefix}/sources/{supported_source}/review', json={
        'status': 'retracted', 'reason': 'Synthetic retraction for regression testing',
    })
    assert retraction.status_code == 200
    historical = api.get(mixed).json()
    assert historical['assessment'] == 'mixed'
    assert supported_source in historical['outdated_sources']
    assert 'Reviewed claim assessment' in api.get(mixed + '.md').text
    current = f"{prefix}/runs/{submit('contradicted-assessment')}/report"
    assert api.get(current).json()['assessment'] == 'contradicted'
    other = TestClient(api.app, headers={'Authorization': 'Bearer ' + KEYS['bob']})
    assert other.get(current).status_code == 404


def test_reviewed_claim_report_lifecycle(tmp_path):
    exercise_claim_run(client(tmp_path))
