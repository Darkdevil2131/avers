"""Real dense embeddings + lexical retrieval, combined by reciprocal rank fusion."""
import hashlib
import json
import os
from pathlib import Path
import threading

MODEL='sentence-transformers/all-MiniLM-L6-v2'

class DenseIndex:
    def __init__(self):
        self.model=None
        self.lock=threading.RLock()
        self.error=None
        self.reranker=None
        self.artifact_hash=None
    def load(self):
        with self.lock:
            return self._load()
    def _load(self):
        if self.model is not None:return self.model
        from fastembed import TextEmbedding
        self.model=TextEmbedding(model_name=MODEL,cache_dir=os.environ.get('ARES_MODEL_CACHE','state/models'),
                                 threads=2,local_files_only=True)
        sha=hashlib.sha256()
        for file in sorted(Path(self.model.model._model_dir).rglob('*')):
            if file.is_file() and file.suffix in {'.onnx','.json'}:
                sha.update(file.name.encode())
                with file.open('rb') as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block)
        self.artifact_hash=sha.hexdigest()
        return self.model
    def embed(self,texts):
        import numpy as np
        with self.lock:
            vectors=np.asarray(list(self.load().embed(texts,batch_size=16)),dtype=np.float32)
        if not np.isfinite(vectors).all():raise ValueError('Nonfinite embeddings')
        return vectors

    def rerank(self,query,texts):
        with self.lock:
            if self.reranker is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
                self.reranker=TextCrossEncoder('Xenova/ms-marco-MiniLM-L-6-v2',cache_dir=os.environ.get('ARES_MODEL_CACHE','state/models'),threads=2,local_files_only=True)
            return list(self.reranker.rerank(query,texts,batch_size=8))

DENSE=DenseIndex()

def hybrid_search(storage,db,project_id,question,limit=8):
    import numpy as np
    lexical=storage.search(db,project_id,question,limit=40)
    rows=[dict(r) for r in db.execute('''SELECT p.*,s.url,s.digest,s.license_status,s.created_at AS retrieved_at,
      coalesce(d.title,s.url) AS title,coalesce(d.study_id,s.url) AS study_id,coalesce(d.origin,'user_supplied') AS origin,
      coalesce((SELECT max(id) FROM source_reviews WHERE source_id=s.id),0) AS review_version
      FROM passages p JOIN sources s ON s.id=p.source_id LEFT JOIN source_details d ON d.source_id=s.id
      WHERE p.project_id=? AND coalesce((SELECT status FROM source_reviews WHERE source_id=s.id ORDER BY id DESC LIMIT 1),'active')='active'
      ORDER BY p.id LIMIT 2001''',(project_id,))]
    if not rows:return [],{'mode':'hybrid','indexed_passages':0,'dense_available':False}
    if len(rows)>2000:
        return lexical[:limit],{'mode':'lexical','reason':'Dense corpus limit exceeded (2000 passages)','dense_available':False}
    try:
        DENSE.load()
        cache_model=MODEL+"@"+DENSE.artifact_hash
        cached={r['passage_id']:r['vector'] for r in db.execute('SELECT * FROM embeddings WHERE project_id=? AND model=?',(project_id,cache_model))}
        missing=[r for r in rows if r['id'] not in cached]
        if missing:
            vectors=DENSE.embed([r['text'] for r in missing])
            for r,v in zip(missing,vectors):
                raw=v.astype('<f4').tobytes();cached[r['id']]=raw
                db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?)',(r['id'],project_id,cache_model,raw,hashlib.sha256(r['text'].encode()).hexdigest()))
        query=DENSE.embed([question])[0]
        from .agents import terms
        adjustments=[]
        current_terms=terms(question)
        for feedback in db.execute("SELECT f.*,r.question FROM feedback f JOIN runs r ON r.id=f.run_id WHERE f.project_id=? ORDER BY f.id DESC LIMIT 100",(project_id,)):
            previous_terms=terms(feedback['question'])
            if len(current_terms & previous_terms)/max(1,len(current_terms|previous_terms))<.4:continue
            matching=[r for r in rows if r['source_id']==feedback['source_id']]
            if matching:
                mean=np.mean([np.frombuffer(cached[r['id']],dtype='<f4') for r in matching],axis=0)
                adjustments.append(mean if feedback['relevant'] else -mean)
        if adjustments:query=query+.1*np.mean(adjustments,axis=0)
        matrix=np.asarray([np.frombuffer(cached[r['id']],dtype='<f4') for r in rows])
        similarity=(matrix@query)/(np.linalg.norm(matrix,axis=1)*np.linalg.norm(query)+1e-12)
        order=np.argsort(-similarity)[:40]
        dense=[dict(rows[i],semantic_similarity=float(similarity[i])) for i in order if similarity[i]>=0.20]
        by_id={r['id']:r for r in rows};scores={}
        for ranking in (lexical,dense):
            for rank,r in enumerate(ranking,1):
                scores[r['id']]=scores.get(r['id'],0)+1/(60+rank)
                by_id[r['id']].update({k:v for k,v in r.items() if k in {'semantic_similarity','rank'}})
        results=[]
        for pid in sorted(scores,key=lambda p:(-scores[p],p))[:24]:
            results.append(dict(by_id[pid],retrieval_score=scores[pid]))
        reranked=False
        try:
            relevance=DENSE.rerank(question,[r['text'] for r in results]) if results else []
            for item,score in zip(results,relevance):item['rerank_score']=float(score)
            results.sort(key=lambda r:-r['rerank_score'])
            reranked=bool(results)
        except (ImportError,OSError,ValueError,RuntimeError):pass
        return results[:limit],{'reviewed_feedback_used':len(adjustments),'reranked':reranked,'mode':'hybrid','dense_available':True,'model':MODEL,'model_sha256':DENSE.artifact_hash,'indexed_passages':len(rows),'fusion':'RRF k=60','similarity_is_truth_probability':False}
    except (ImportError,OSError,ValueError,RuntimeError) as exc:
        return lexical[:limit],{'mode':'lexical','dense_available':False,'reason':'Embedding model unavailable; run model preparation on the host','error_type':type(exc).__name__}
