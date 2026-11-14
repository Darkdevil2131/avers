"""Boundary tests with mocked inference, not scientific/model accuracy tests."""
import json
from types import SimpleNamespace
import pytest
from ares import local_reasoner as reasoner

QUOTE='The measured coating adhesion decreased.'


def invoke(tmp_path,monkeypatch,payload,citations):
    model=tmp_path/'fixture.gguf';model.write_text('Never loaded')
    monkeypatch.setenv('ARES_REASONER_MODEL',str(model))
    monkeypatch.setattr(reasoner.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps(payload)))
    return reasoner.suggest('Coating adhesion',citations)


def proposal(label='S1',quote=QUOTE,answer=QUOTE):
    return {'model_sha256':'fixture','proposal':{'answer':answer,'hypothesis':'Adhesion may decrease.',
        'mechanism':'Requires review','falsification':'Controlled comparison','citation':label,
        'quote':quote,'limitations':['Synthetic fixture']}}


def citation(label='S1',quote=QUOTE,origin='user_supplied'):
    return {'label':label,'source_id':label,'quote':quote,'origin':origin}


@pytest.mark.parametrize('payload',[None,[],42,'text',{'proposal':None},{'proposal':[]}])
def test_invalid_envelopes_and_proposals_are_rejected(tmp_path,monkeypatch,payload):
    result=invoke(tmp_path,monkeypatch,payload,[citation()])
    assert result['status']=='rejected'
    assert result['proposals']==[]


@pytest.mark.parametrize('excluded',[False,True])
def test_unseen_or_metadata_citation_cannot_ground_proposal(tmp_path,monkeypatch,excluded):
    citations=[citation('S1'),citation('S2'),citation('S3'),citation('S4',origin='europepmc_metadata' if excluded else 'user_supplied')]
    result=invoke(tmp_path,monkeypatch,proposal('S4'),citations)
    assert result['status']=='rejected'
    assert 'supplied to the model' in result['reason']


def test_quote_outside_sent_excerpt_is_rejected(tmp_path,monkeypatch):
    result=invoke(tmp_path,monkeypatch,proposal(),[citation(quote='x'*900+QUOTE)])
    assert result['status']=='rejected'


def test_answer_outside_sent_excerpt_is_not_published(tmp_path,monkeypatch):
    unseen='A different observation outside the model context.'
    result=invoke(tmp_path,monkeypatch,proposal(answer=unseen),[citation(quote=QUOTE+'x'*900+unseen)])
    assert result['status']=='completed'
    assert result['answer'] is None


def test_supplied_exact_quote_remains_candidate_only(tmp_path,monkeypatch):
    result=invoke(tmp_path,monkeypatch,proposal(),[citation()])
    assert result['status']=='completed'
    assert result['answer']==QUOTE
    assert result['scientific_validity']=='unvalidated'
