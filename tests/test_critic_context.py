"""Synthetic regression cases; these are not a scientific accuracy benchmark."""
import pytest
from ares.agents import proposal_critic


@pytest.mark.parametrize('statement,quote', [
    ('Coating adhesion did not increase.', 'Coating adhesion decreased.'),
    ('Coating adhesion decreased.', 'Coating adhesion did not increase.'),
    ('Coating adhesion increased.', 'Coating adhesion did not decrease.'),
    ('Coating adhesion increased.', 'Coating adhesion showed no significant decrease.'),
    ("Coating adhesion didn't increase.", 'Coating adhesion decreased.'),
    ('Coating adhesion failed to increase.', 'Coating adhesion decreased.'),
])
def test_negation_does_not_turn_into_an_opposite_effect(statement,quote):
    result=proposal_critic({'statement':statement,'basis_quote':quote,'mechanism':'Requires investigation'})
    assert result['accepted_as_candidate']
    assert result['direction_check']['status']=='requires_review'
    assert not result['direction_check']['context_verified']
    assert not result['scientific_validation']


@pytest.mark.parametrize('statement,quote', [
    ('Coating adhesion increased at lower humidity.', 'Coating adhesion decreased at lower humidity.'),
    ('Coating adhesion decreased at higher humidity.', 'Coating adhesion increased at higher humidity.'),
    ('Coating adhesion was higher.', 'Coating adhesion was lower.'),
])
def test_exposure_comparatives_do_not_hide_explicit_opposition(statement,quote):
    result=proposal_critic({'statement':statement,'basis_quote':quote,'mechanism':'Requires investigation'})
    assert not result['accepted_as_candidate']
    assert result['direction_check']['status']=='potential_opposition'
    assert not result['scientific_validation']


def test_multiple_directions_are_not_collapsed_into_a_verdict():
    result=proposal_critic({'statement':'Coating adhesion increased.',
                           'basis_quote':'Coating adhesion decreased, but coating strength increased.',
                           'mechanism':'Requires investigation'})
    assert result['accepted_as_candidate']
    assert result['direction_check']['status']=='requires_review'


def test_mechanism_disclaimer_still_rejects_when_direction_is_ambiguous():
    result=proposal_critic({'statement':'Coating adhesion did not increase.',
                           'basis_quote':'Coating adhesion decreased.',
                           'mechanism':'This contradicts the evidence.'})
    assert not result['accepted_as_candidate']
    assert result['reasons']==['The generated mechanism explicitly disclaims its own evidential support']
