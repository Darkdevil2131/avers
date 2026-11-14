"""Synthetic review-routing cases, not scientific accuracy evaluation."""
from ares.agents import critique
from ares.report_export import export_markdown
from test_evidence import CONTEXT
from test_research import client, project, run


def review(left,right,same_study=False,same_source=False):
    findings=[{'source_id':'a','citation':'S1','statement':left},
              {'source_id':'a' if same_source else 'b','citation':'S2','statement':right}]
    citations=[{'label':'S1','url':'https://example.org/a','study_id':'study-a'},
               {'label':'S2','url':'https://example.org/b','study_id':'study-a' if same_study else 'study-b'}]
    return critique(findings,citations)


def test_opposing_effects_are_reviewed_with_exact_statements():
    left='Coating adhesion increased after high humidity exposure.'
    right='Coating adhesion decreased after high humidity exposure.'
    result=review(left,right)
    pair=result['potential_disagreements'][0]
    assert pair['signal']=='opposing_direction'
    assert pair['left_statement']==left and pair['right_statement']==right
    assert not pair['context_verified'] and not pair['automatic_verdict']
    assert len(pair['review_questions'])==4
    assert result['decision']=='abstain_from_scientific_verdict'
    export=export_markdown('# Report',{'critique':result},[])
    assert left in export and right in export and pair['review_questions'][0] in export


def test_matching_directions_and_unrelated_outcomes_are_not_flagged():
    assert review('Coating adhesion increased after humidity exposure.',
                  'Coating adhesion increased after humidity exposure.')['potential_disagreements']==[]
    assert review('Coating adhesion increased after humidity exposure.',
                  'Mortality decreased in the clinical trial.')['potential_disagreements']==[]


def test_shared_study_identifier_is_disclosed_not_claimed_independent():
    result=review('Coating adhesion increased after humidity exposure.',
                  'Coating adhesion decreased after humidity exposure.',same_study=True)
    assert result['potential_disagreements'][0]['same_study_identifier']
    assert result['study_identifier_groups']==[['S1','S2']]
    assert not result['independence_verified']
    assert 'do not count them as independent' in export_markdown('# Report',{'critique':result},[])


def test_existing_negation_signal_still_requires_review():
    pair=review('Coating adhesion did not increase after humidity exposure.',
                'Coating adhesion increased after humidity exposure.')['potential_disagreements'][0]
    assert pair['signal']=='different_negation' and not pair['automatic_verdict']


def test_same_source_is_not_called_cross_source_disagreement():
    assert review('Coating adhesion increased after humidity exposure.',
                  'Coating adhesion decreased after humidity exposure.',same_source=True)['potential_disagreements']==[]


def test_report_uses_exact_reviews_to_distinguish_context_mismatch(tmp_path):
    check_report_context(client(tmp_path))


def check_report_context(api):
    project_id = project(api)
    prefix = f'/projects/{project_id}'
    observations = [
        'Coating stability increased after exposure to humidity during the controlled test.',
        'Coating stability decreased after exposure to humidity during the controlled test.',
    ]
    sources = []
    for i, observation in enumerate(observations):
        response = api.post(f'{prefix}/sources', json={
            'url': f'https://example.org/coating-{i}', 'title': f'Coating test {i}',
            'text': observation, 'license_status': 'Synthetic fixture',
        })
        assert response.status_code == 201
        sources.append(response.json()['id'])

    claim = api.post(f'{prefix}/claims', json={
        'statement': 'Humidity affects coating stability.', 'fingerprint': CONTEXT,
    }).json()['id']

    def link(index, fingerprint, start=0):
        response = api.post(f'{prefix}/claims/{claim}/evidence', json={
            'source_id': sources[index], 'start_offset': start, 'end_offset': len(observations[index]),
            'stance': 'neutral', 'fingerprint': fingerprint, 'rationale': 'Synthetic reviewed context',
        })
        assert response.status_code == 201

    def get_pair():
        report_route = f'{prefix}/runs/{run(api, project_id)}/report'
        response = api.get(report_route)
        assert response.status_code == 200
        report = response.json()
        assert report['assessment'] == 'inconclusive'
        pair = report['critique']['potential_disagreements'][0]
        assert pair['automatic_verdict'] is False
        return pair['reviewed_context'], report_route

    link(0, CONTEXT)
    link(1, CONTEXT, start=1)
    context, _ = get_pair()
    assert context['state'] == 'unverified' and context['review_ids'] == []

    link(1, {**CONTEXT, 'units': 'mpa', 'conditions': '90 C'})
    context, route = get_pair()
    assert context['state'] == 'context-mismatched'
    assert context['fields'] == ['units', 'conditions']
    assert context['claim_ids'] == [claim] and len(context['review_ids']) == 2
    assert 'Reviewed context: context-mismatched.' in api.get(route + '.md').text

    link(1, CONTEXT)
    context, _ = get_pair()
    assert context['state'] == 'review-conflict'
    assert len(context['review_ids']) == 3
    assert api.get(route).json()['critique']['potential_disagreements'][0]['reviewed_context']['state'] == 'context-mismatched'
