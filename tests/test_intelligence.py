import json
import pytest
from ares.documents import parse_jats
from ares.agents import extract, critique, plan
from ares.retrieval import hybrid_search, DENSE
from test_research import client, project, source, run

XML=b'''<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><article-title>Humidity experiment</article-title><permissions><license><ext-link xlink:href="https://creativecommons.org/licenses/by/4.0/"/></license></permissions></article-meta></front><body><sec><p id="p1">Humidity reduced coating stability by 20% in the controlled experiment.</p></sec></body><back><ref-list><ref><pub-id pub-id-type="pmcid">PMC123</pub-id></ref></ref-list></back></article>'''

def test_rights_gated_fulltext_and_locations():
    doc=parse_jats(XML,'PMC123')
    assert doc['origin']=='europepmc_fulltext'
    for loc in doc['document']['locations']:assert doc['text'][loc['start']:loc['end']].startswith('Humidity')
    assert doc['document']['references']==['PMC123']
    with pytest.raises(ValueError):parse_jats(XML.replace(b'https://creativecommons.org/licenses/by/4.0/',b'https://example.org/license'),'PMC123')
    with pytest.raises(Exception):parse_jats(b'<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><article>&leak;</article>','PMC1')

def test_extraction_exact_span_and_candidate_only():
    quote='  Humidity reduced the coating stability by 20%. Other words.'
    citations=[{'source_id':'s','label':'S1','quote':quote,'start_offset':0,'origin':'user_supplied','url':'fixture'}]
    result=extract(citations,'humidity coating stability')
    assert len(result)==1
    item=result[0]
    assert quote[item['start_offset']:item['end_offset']]==item['statement']
    assert item['status']=='candidate' and item['context_verified'] is False
    assert critique(result,citations)['decision']=='abstain_from_scientific_verdict'

def test_spider_follows_references_with_bounded_cycle_and_real_events(tmp_path):
    class Provider:
        def __init__(self):self.fetched=[]
        def search(self,q):return [dict(parse_jats(XML,'PMC1'),pmcid='PMC1',is_open_access=True)]
        def fulltext(self,p):self.fetched.append(p);return parse_jats(XML,p)
    provider=Provider();c=client(tmp_path,provider=provider);pid=project(c);rid=run(c,pid,external=True)
    assert provider.fetched==['PMC1','PMC123']
    events=c.get(f'/projects/{pid}/runs/{rid}/events').json()
    assert [e['payload']['depth'] for e in events if e['stage']=='spider_fetch']==[0,1]
    report=c.get(f'/projects/{pid}/runs/{rid}/report').json()
    assert report['findings'] and report['hypotheses']
    assert report['hypotheses'][0]['experiment_executed'] is False

def test_memory_requires_review_and_retraction_blocks_approval(tmp_path):
    c=client(tmp_path);pid=project(c);s=source(c,pid);rid=run(c,pid)
    memory=c.get(f'/projects/{pid}/memory').json()[0]
    assert memory['status']=='pending'
    assert c.post(f"/projects/{pid}/memory/{memory['id']}/review",json={'status':'active','reason':'Reviewed source and report'}).status_code==200
    c.post(f"/projects/{pid}/sources/{s['id']}/review",json={'status':'retracted','reason':'Publisher retraction notice'})
    assert c.get(f'/projects/{pid}/memory').json()[0]['stale'] is True
    assert c.post(f"/projects/{pid}/memory/{memory['id']}/review",json={'status':'active','reason':'Try to approve stale memory'}).status_code==409

def test_model_unavailable_is_visible_and_scope_is_preserved(tmp_path,monkeypatch):
    c=client(tmp_path);pid=project(c);source(c,pid);other=project(c);source(c,other,'A secret unrelated study on coating.')
    monkeypatch.setattr(DENSE,'embed',lambda _: (_ for _ in ()).throw(ValueError('offline')))
    result=c.get(f'/projects/{pid}/retrieve',params={'q':'coating'}).json()
    assert result['retrieval']['mode']=='lexical'
    assert all(p['project_id']==pid for p in result['passages'])

def test_local_reasoner_rejects_invented_citations_without_tools(tmp_path,monkeypatch):
    from ares import local_reasoner
    from types import SimpleNamespace
    model=tmp_path/'fixture.gguf';model.write_text('fixture path; never loaded')
    monkeypatch.setenv('ARES_REASONER_MODEL',str(model))
    data={'answer':'Unsupported answer','hypothesis':'A candidate','mechanism':'A mechanism','falsification':'A falsification test','citation':'INVENTED','quote':'Text not present in any source','limitations':[]}
    captured={}
    def fake_run(*args,**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0,stdout=json.dumps({'proposal':data,'model_sha256':'fixture'}))
    monkeypatch.setattr(local_reasoner.subprocess,'run',fake_run)
    monkeypatch.setenv('ARES_CREDENTIALS','secret should not enter child process')
    result=local_reasoner.suggest('Question',[{'label':'S1','source_id':'s','origin':'user_supplied','quote':'Original factual source text for the test.'}])
    assert result['status']=='rejected'
    assert 'ARES_CREDENTIALS' not in captured['env']
    assert captured['timeout']==90

def test_feedback_is_citation_scoped_and_never_updates_truth(tmp_path):
    c=client(tmp_path);pid=project(c);s=source(c,pid);rid=run(c,pid)
    route=f'/projects/{pid}/runs/{rid}/feedback'
    assert c.post(route,json={'source_id':'unknown','relevant':True}).status_code==422
    result=c.post(route,json={'source_id':s['id'],'relevant':True})
    assert result.status_code==200 and result.json()['truth_updated'] is False
    with c.app.state.storage.connect() as db:
        assert db.execute('SELECT count(*) FROM feedback').fetchone()[0]==1
    c.post(route,json={'source_id':s['id'],'relevant':False})
    with c.app.state.storage.connect() as db:
        assert db.execute('SELECT relevant FROM feedback').fetchone()[0]==0

def test_proposal_critic_rejects_observed_model_failure():
    from ares.agents import proposal_critic
    result=proposal_critic({'statement':'Coating adhesion increases with higher humidity.','basis_quote':'Coating adhesion decreased after exposure to high humidity.','mechanism':'This is not supported by the evidence.'})
    assert result['accepted_as_candidate'] is False and len(result['reasons'])==2
    assert result['scientific_validation'] is False

def test_original_xml_is_retained_with_matching_hash():
    import base64,hashlib
    doc=parse_jats(XML,'PMC123')['document']
    raw=base64.b64decode(doc['original_xml_base64'])
    assert raw==XML and hashlib.sha256(raw).hexdigest()==doc['original_sha256']

def test_bioc_requires_matching_identity_and_license():
    from ares.documents import parse_bioc
    import base64,hashlib
    data=[{'documents':[{'id':'PMC1','infons':{'license':'CC BY'},'passages':[{'offset':0,'infons':{'type':'paragraph','section_type':'RESULTS'},'text':'Coating adhesion decreased under high humidity.'}]}]}]
    raw=json.dumps(data).encode();doc=parse_bioc(raw,'PMC1')
    assert doc['text']=='Coating adhesion decreased under high humidity.'
    assert base64.b64decode(doc['document']['original_content_base64'])==raw
    with pytest.raises(ValueError):parse_bioc(raw,'PMC2')
    data[0]['documents'][0]['infons']['license']='All rights reserved'
    with pytest.raises(ValueError):parse_bioc(json.dumps(data).encode(),'PMC1')
