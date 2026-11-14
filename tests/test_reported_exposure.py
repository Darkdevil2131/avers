import json
from pathlib import Path

import pytest

from ares.exposure import compare_exposure, extract_exposure
from test_research import client, project, run


@pytest.mark.parametrize('statement', [
    'Coating stability increased after exposure at 25–40 °C and 80% RH.',
    'Coating stability would increase if tested at 40 °C and 80% RH.',
    'Coating stability increased after testing at 40 °C or 25 °C.',
    'Coating stability increased at 25 °C after testing at 40 °C.',
    'Coating stability increased after cyclic exposure at 40 °C and 80% RH.',
    'Coating stability increased after exposure at 80%.',
    'Coating stability increased after testing at 110% RH.',
    'Coating stability increased after exposure at −300 °C.',
    'Some samples were not conditioned at 25 °C and 50% RH for 48 h before testing.',
    'One group was held at 80% RH while samples were conditioned at 25 °C and 50% RH for 48 h before testing.',
    'Film strips were conditioned at 25 °C and 50% relative humidity for at least 48 h prior to testing.',
])
def test_ambiguous_or_invalid_exposure_is_unresolved(statement):
    assert extract_exposure(statement, 0) == {}


PUBLISHED_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / 'benchmarks/materials_exposure.json').read_text()
)['cases']


@pytest.mark.parametrize('case', PUBLISHED_CASES, ids=lambda case: case['id'])
def test_published_wording_preserves_expected_values_and_offsets(case):
    statement = case['text']
    prefix = 'Methods. '
    document = prefix + statement
    exposure = extract_exposure(statement, len(prefix))
    assert {field: entry['value'] for field, entry in exposure.items()} == case['expected']
    for entry in exposure.values():
        assert document[entry['start_offset']:entry['end_offset']] == entry['quote']


def test_conditioning_setpoints_are_not_compared_to_exposure_setpoints():
    conditioned = extract_exposure('Samples were conditioned for 48 h at 25 °C and 50% RH before testing.', 0)
    exposed = extract_exposure('Samples were exposed at 25 °C and 50% RH for 48 h.', 0)
    assert conditioned['temperature']['stage'] == 'conditioning'
    assert exposed['temperature']['stage'] == 'exposure'
    assert compare_exposure({'reported_exposure': conditioned}, {'reported_exposure': exposed}) == []


def test_report_compares_stated_conditions_with_exact_source_offsets(tmp_path):
    api = client(tmp_path)
    project_id = project(api)
    prefix = f'/projects/{project_id}'
    texts = {}
    for i, (direction, temperature, duration) in enumerate([
        ('increased', '25', '2 days'), ('decreased', '40', '48 h'),
    ]):
        observation = (
            f'Coating stability {direction} after humidity exposure '
            f'at {temperature} °C and 80% RH for {duration}.'
        )
        document = '  Methods summary. ' + observation
        source = api.post(f'{prefix}/sources', json={
            'url': f'https://example.org/exposure-{i}', 'title': f'Exposure fixture {i}',
            'text': document, 'license_status': 'Synthetic fixture',
        })
        assert source.status_code == 201
        texts[source.json()['id']] = document

    route = f'{prefix}/runs/{run(api, project_id)}/report'
    response = api.get(route)
    assert response.status_code == 200
    report = response.json()
    assert report['assessment'] == 'inconclusive'
    pair = report['critique']['potential_disagreements'][0]
    assert pair['reviewed_context']['state'] == 'unverified'
    assert pair['context_verified'] is False
    assert pair['automatic_verdict'] is False
    assert {item['field']: item['state'] for item in pair['reported_exposure_comparison']} == {
        'temperature': 'differs', 'relative_humidity': 'matches', 'duration': 'matches',
    }
    for finding in report['findings']:
        for span in finding['reported_exposure'].values():
            assert span['start_offset'] > finding['start_offset']
            assert texts[finding['source_id']][span['start_offset']:span['end_offset']] == span['quote']
    assert 'Reported temperature differs:' in api.get(route + '.md').text
