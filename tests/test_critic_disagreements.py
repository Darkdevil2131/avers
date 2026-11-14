"""Synthetic review-routing cases, not scientific accuracy evaluation."""
from ares.agents import critique
from ares.report_export import export_markdown


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
