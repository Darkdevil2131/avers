from ares.text_spans import sentence_spans,complete_passage
from ares.retrieval import expand_passages
from ares.agents import extract
from ares.retrieval import DENSE

def test_decimal_abbreviation_and_lowercase_sentence_offsets():
    text='Dr. Smith measured 2.5 mg. e.g. values varied. p53 expression decreased by 20%.'
    sentences=[text[a:b] for a,b in sentence_spans(text)]
    assert sentences==['Dr. Smith measured 2.5 mg.','e.g. values varied.','p53 expression decreased by 20%.']
    a,b=complete_passage(text,10,30)
    assert text[a:b]=='Dr. Smith measured 2.5 mg. e.g. values varied.'

def test_expansion_does_not_cross_source_or_duplicate_spans(tmp_path):
    from ares.database import Database
    dbs=Database(tmp_path/'test.db')
    text='First complete sentence about humidity. Second complete sentence about coating.'
    with dbs.connect() as db:
        db.execute("INSERT INTO projects VALUES('p','alice','Fixture')")
        source=dbs.add_source(db,'p',{'url':'https://example.org','text':text,'license_status':'fixture'},'alice')
        p={'source_id':source['id'],'start_offset':10,'end_offset':25}
        result=expand_passages(db,[p,p])
    assert len(result)==1
    assert result[0]['text']=='First complete sentence about humidity.'
    assert text[result[0]['start_offset']:result[0]['end_offset']]==result[0]['text']

def test_candidate_budget_is_global(monkeypatch):
    sizes=[]
    def score(q,values):sizes.append(len(values));return [1.0]*len(values)
    monkeypatch.setattr(DENSE,'rerank',score)
    citations=[{'source_id':str(i),'label':f'S{i}','quote':' '.join(f'Humidity reduced coating stability in experiment {n}.' for n in range(100)),'start_offset':0} for i in range(8)]
    result=extract(citations,'humidity coating')
    assert sizes==[80] and len(result)==3

def test_context_relevance_breaks_sentence_only_tie_without_truth_claim(monkeypatch):
    monkeypatch.setattr(DENSE,'rerank',lambda q,values:[2.0]*len(values))
    citations=[{'source_id':'weak','label':'S1','quote':'Humidity reduced coating stability in one experiment.','start_offset':0,'rerank_score':-2.0},
               {'source_id':'strong','label':'S2','quote':'Humidity reduced coating stability in another experiment.','start_offset':0,'rerank_score':6.0}]
    findings=extract(citations,'humidity coating')
    assert findings[0]['source_id']=='strong'
    assert findings[0]['context_verified'] is False
    assert findings[0]['status']=='candidate'
