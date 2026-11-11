"""Independent-label retrieval/extraction evaluation on a preselected SciFact subset.
Never imports gold labels into retrieval or training. Does not validate scientific reasoning.
"""
import hashlib,io,json,random,tarfile,time,urllib.request,os
from pathlib import Path
from ares.database import Database
from ares.retrieval import hybrid_search
from ares.agents import extract

SEED=int(os.environ.get('ARES_EVAL_SEED','20261111'))
OUTPUT=os.environ.get('ARES_EVAL_OUTPUT','docs/scifact-evaluation.json')
ROOT=Path('state/scifact-evaluation-'+str(SEED));ROOT.mkdir(parents=True,exist_ok=True)
archive=ROOT/'data.tar.gz'
if not archive.exists():
    with urllib.request.urlopen('https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz',timeout=45) as response:raw=response.read(20_000_001)
    if len(raw)>20_000_000:raise SystemExit('Dataset exceeded download limit')
    archive.write_bytes(raw)
raw=archive.read_bytes()
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tar:
    def records(name):
        member=next(x for x in tar.getmembers() if x.name==f'data/{name}' and x.isfile())
        if member.size>20_000_000:raise ValueError('Dataset member over budget')
        return [json.loads(line) for line in tar.extractfile(member) if line.strip()]
    corpus=records('corpus.jsonl');claims=records('claims_dev.jsonl')
random.Random(SEED).shuffle(corpus)
corpus=corpus[:1000];allowed={str(d['doc_id']) for d in corpus}
claims=[c for c in claims if c.get('evidence') and set(c['evidence'])<=allowed]
exclude_path=os.environ.get('ARES_EVAL_EXCLUDE')
excluded={r['claim_id'] for r in json.loads(Path(exclude_path).read_text())['results']} if exclude_path else set()
claims=[c for c in claims if c['id'] not in excluded]
random.Random(42).shuffle(claims);claims=claims[:30]
if not claims:raise SystemExit('No evaluable claims in the preregistered document subset')
path=ROOT/'evaluation.db'
if path.exists():path.unlink()
dbs=Database(path);lookup={};documents={str(d['doc_id']):d for d in corpus}
with dbs.connect() as db:
    db.execute("INSERT INTO projects VALUES('benchmark','evaluation','SciFact restricted corpus')")
    for d in corpus:
        source=dbs.add_source(db,'benchmark',{'url':f"https://scifact.apps.allenai.org/corpus/{d['doc_id']}",'title':d['title'],'text':' '.join(d['abstract']),'license_status':'S2ORC ODC-By 1.0; SciFact evaluation corpus','study_id':str(d['doc_id']),'origin':'benchmark_abstract'},'evaluation')
        lookup[source['id']]=str(d['doc_id'])
    count=db.execute('SELECT count(*) FROM passages').fetchone()[0]
print(json.dumps({'phase':'index','documents':len(corpus),'passages':count,'queries':len(claims)}),flush=True)
results=[];start=time.monotonic()
with dbs.connect() as db:
    for index,c in enumerate(claims):
        gold=set(c['evidence'])
        lexical=dbs.search(db,'benchmark',c['claim'],limit=8)
        passages,detail=hybrid_search(dbs,db,'benchmark',c['claim'],limit=8)
        cites=[dict(p,label=f'S{i+1}',quote=p['text']) for i,p in enumerate(passages)]
        candidates=extract(cites,c['claim'])
        rationale={}
        for doc_id,groups in c['evidence'].items():
            indices=set(n for group in groups for n in group['sentences'])
            rationale[doc_id]=[documents[doc_id]['abstract'][n] for n in indices]
        correct=0;top1=False
        for candidate_index,f in enumerate(candidates):
            targets=rationale.get(lookup[f['source_id']],[])
            if any(f['statement'] in sentence or sentence in f['statement'] for sentence in targets):
                correct+=1
                if candidate_index==0:top1=True
        results.append({'claim_id':c['id'],'gold_documents':sorted(gold),'lexical_recall8':len({lookup[p['source_id']] for p in lexical}&gold)/len(gold),
                        'hybrid_recall8':len({lookup[p['source_id']] for p in passages}&gold)/len(gold),
                        'retrieval_mode':detail['mode'],'reranked':detail.get('reranked',False),'extracted_candidates':len(candidates),'rationale_matching_candidates':correct,'first_candidate_matches_rationale':top1})
        print(json.dumps({'phase':'query','done':index+1,'total':len(claims)}),flush=True)
summary={'dataset':'SciFact development split restricted to independently preselected 1000-document corpus',
 'source':'https://github.com/allenai/scifact','license':'https://github.com/allenai/scifact/blob/master/LICENSE.md',
 'archive_sha256':hashlib.sha256(raw).hexdigest(),'document_seed':SEED,'excluded_prior_claim_ids':sorted(excluded),'query_seed':42,'documents':len(corpus),'passages':count,'queries':len(claims),
 'selection':'Shuffle corpus with fixed seed, keep 1000 documents; retain development claims whose complete gold evidence is in that corpus; shuffle eligible claims and take up to 30. Gold is used only for selection and scoring.',
 'limitations':['Restricted-corpus evaluation is easier than full SciFact retrieval','Development set, not hidden official test set','Pretrained weights unchanged; extraction selection was revised after observing the baseline development result, so this is development evaluation, not an independent final acceptance test','This does not validate truth assessment, causal reasoning, or hypothesis quality','Extraction precision is exact sentence containment and does not measure semantic equivalence'],
 'lexical_macro_recall8':sum(x['lexical_recall8'] for x in results)/len(results),'hybrid_macro_recall8':sum(x['hybrid_recall8'] for x in results)/len(results),
 'candidate_rationale_precision':sum(x['rationale_matching_candidates'] for x in results)/max(1,sum(x['extracted_candidates'] for x in results)),
 'first_candidate_rationale_accuracy':sum(x['first_candidate_matches_rationale'] for x in results)/len(results),'hybrid_active_queries':sum(x['retrieval_mode']=='hybrid' for x in results),'reranked_queries':sum(x['reranked'] for x in results),'seconds':time.monotonic()-start,'results':results}
Path(OUTPUT).write_text(json.dumps(summary,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k!='results'},indent=2),flush=True)
