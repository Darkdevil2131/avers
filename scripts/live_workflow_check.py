"""Real keyless full text -> HTTP API -> separate worker -> model-assisted RAG report.
Runs only against a temporary local database; no cloud provisioning or paid APIs.
"""
import hashlib,json,os,secrets,socket,subprocess,sys,tempfile,time
from pathlib import Path
import httpx
from ares.providers import EuropePMC

def main():
    source=EuropePMC().fulltext('PMC4383902')
    with tempfile.TemporaryDirectory(prefix='ares-live-workflow-') as temp:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        token=secrets.token_urlsafe(48)
        env=dict(os.environ,ARES_DATABASE=str(Path(temp)/'live.db'),ARES_QUEUE_MODE='db',ARES_CREDENTIALS=json.dumps({'check':token}))
        env.pop('ARES_REASONER_MODEL',None);env.pop('ARES_WORKER_DATABASE',None)
        worker_env=dict(env);worker_env.pop('ARES_CREDENTIALS')
        processes=[];started=time.monotonic()
        with open(Path(temp)/'services.log','w') as log:
            try:
                processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','ares.api:app_factory','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],env=env,stdout=log,stderr=log))
                with httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+token},timeout=15) as client:
                    for _ in range(60):
                        try:
                            if client.get('/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.5)
                    else:raise RuntimeError('HTTP startup failed')
                    def post(path,value):
                        r=client.post(path,json=value);r.raise_for_status();return r.json()
                    pid=post('/projects',{'name':'Real full-text workflow check'})['id']
                    imported=post(f'/projects/{pid}/sources',source)
                    rid=post(f'/projects/{pid}/runs',{'question':source['title'][:500],'external':False})['id']
                    processes.append(subprocess.Popen([sys.executable,'-m','ares.cli','worker'],env=worker_env,stdout=log,stderr=log))
                    deadline=time.monotonic()+180
                    while time.monotonic()<deadline:
                        state=client.get(f'/projects/{pid}/runs/{rid}').json()
                        if state['status']=='completed':break
                        if state['status']=='failed':raise RuntimeError('Research worker failed')
                        time.sleep(.5)
                    else:raise RuntimeError('Worker deadline exceeded')
                    response=client.get(f'/projects/{pid}/runs/{rid}/report');response.raise_for_status();report=response.json()
                    events=client.get(f'/projects/{pid}/runs/{rid}/events').json()
                    retrieval=next(e['payload'] for e in events if e['stage']=='memory_retrieval')
                    assert retrieval['mode']=='hybrid' and retrieval['reranked']
                    assert report['citations'] and report['assessment']=='inconclusive'
                    for c in report['citations']:
                        assert c['source_id']==imported['id']
                        assert c['quote']==source['text'][c['start_offset']:c['end_offset']]
                        assert c['digest']==hashlib.sha256(source['text'].encode()).hexdigest()
                    for f in report['findings']:assert f['statement']==source['text'][f['start_offset']:f['end_offset']]
                    result={'passed':True,'pmcid':'PMC4383902','provider':source['origin'],'license':source['license_status'],'original_sha256':source['document']['original_sha256'],
                        'characters':len(source['text']),'citation_count':len(report['citations']),'finding_count':len(report['findings']),'retrieval':retrieval,'reasoner':report['reasoner'],'seconds_after_collection':time.monotonic()-started,
                        'scope':'Real licensed full text ingested via HTTP; separate worker; prepared local dense/reranking models; persisted exact citations',
                        'limits':['SQLite in hosted test workspace, not public deployment','Question uses article title; no answer correctness metric','Generative reasoner deliberately disabled and disclosed','No production SLA or permanent hosting established']}
                    Path('docs/live-workflow-verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
            finally:
                for p in processes:p.terminate()
                for p in processes:
                    try:p.wait(timeout=10)
                    except subprocess.TimeoutExpired:p.kill();p.wait()
if __name__=='__main__':main()
