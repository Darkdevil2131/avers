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


def test_neighbor_ranking_keeps_exact_candidate_offsets(monkeypatch):
    setup = 'We exposed a protective coating to high humidity.'
    result = 'These samples lost adhesion after seven days.'
    unrelated = 'These samples received identifiers before the experiment.'
    text = f'{setup} {result}\n{unrelated}'
    batches = []

    def score(question, texts):
        batches.append(texts)
        return [3.0] if len(batches) == 2 else [1.0, -1.0]

    monkeypatch.setattr(DENSE, 'rerank', score)
    citation = {'source_id': 'coating', 'label': 'S1', 'quote': text, 'start_offset': 10}
    first, other = extract([citation], 'Does humidity affect the coating?')
    assert batches == [[setup, result], [f'{result} {setup}']]
    assert first['statement'] == result
    assert first['neighbor_relevance_score'] == 3.0
    assert text[first['start_offset'] - 10:first['end_offset'] - 10] == result
    assert not first['context_verified'] and other['statement'] == setup


def test_failed_context_scoring_keeps_direct_matches_only(monkeypatch):
    setup = 'Humidity reduced coating stability during a chamber test.'
    result = 'These samples lost adhesion after seven days.'

    def score(question, texts):
        if len(texts) == 1:
            raise RuntimeError('Context reranking unavailable')
        return [1.0, 10.0]

    monkeypatch.setattr(DENSE, 'rerank', score)
    citation = {'source_id': 'coating', 'label': 'S1', 'quote': f'{setup} {result}', 'start_offset': 0}
    direct, = extract([citation], 'Does humidity affect the coating?')
    assert direct['statement'] == setup
