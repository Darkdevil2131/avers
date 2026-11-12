"""Paired development regression check; gold never enters ranking functions.
Requires the saved 20261112 SciFact evaluation DB/archive and unchanged model cache.
"""
import importlib.util,json,os,tarfile,time
from pathlib import Path
from ares.database import Database
from ares.retrieval import _hybrid_search,expand_passages
from ares.agents import extract
root=Path(os.environ['ARES_PRIOR_EVAL'])
spec=importlib.util.spec_from_file_location('ares.baseline_agents','state/baseline_agents.py')
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
prior=json.loads(Path('docs/scifact-independent-check.json').read_text())
with tarfile.open(root/'data.tar.gz') as tar:
    claims={c['id']:c for c in (json.loads(l) for l in tar.extractfile('data/claims_dev.jsonl'))}
    corpus={str(c['doc_id']):c for c in (json.loads(l) for l in tar.extractfile('data/corpus.jsonl'))}
dbs=Database(root/'evaluation.db');results=[];started=time.monotonic()
with dbs.connect() as db:
    lookup={r['source_id']:r['study_id'] for r in db.execute('SELECT source_id,study_id FROM source_details')}
    for item in prior['results']:
        claim=claims[item['claim_id']]
        raw,details=_hybrid_search(dbs,db,'benchmark',claim['claim'])
        if details.get('mode')!='hybrid' or not details.get('reranked'):raise RuntimeError('Real models required')
        expanded=expand_passages(db,raw)
        scored={}
        for name,passages,fn in [('before',raw,baseline.extract),('after',expanded,extract)]:
            citations=[dict(p,label=f'S{i+1}',quote=p['text']) for i,p in enumerate(passages)]
            findings=fn(citations,claim['claim']);matches=[]
            for f in findings:
                docid=lookup[f['source_id']]
                indices={n for group in claim['evidence'].get(docid,[]) for n in group['sentences']}
                sentences=[corpus[docid]['abstract'][n] for n in indices]
                matches.append(any(f['statement'] in s or s in f['statement'] for s in sentences))
                text=db.execute('SELECT text FROM sources WHERE id=?',(f['source_id'],)).fetchone()[0]
                assert text[f['start_offset']:f['end_offset']]==f['statement']
            scored[name]={'top1':bool(matches and matches[0]),'correct':sum(matches),'candidates':len(matches)}
        results.append({'claim_id':claim['id'],**scored})
        print(json.dumps({'done':len(results),'total':30}),flush=True)
summary={'scope':'Paired development regression on the previously inspected 30-claim sample, not independent acceptance','claims':len(results),'corpus_documents':1000,'pipeline_change':'Bounded sentence expansion with exact offsets; abbreviation-aware splitting; global candidate cap','results':results,'seconds':time.monotonic()-started}
for name in ['before','after']:
    summary[name]={'first_candidate_correct':sum(r[name]['top1'] for r in results),'candidate_precision':sum(r[name]['correct'] for r in results)/sum(r[name]['candidates'] for r in results)}
Path('docs/sentence-boundary-evaluation.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='results'},indent=2))
