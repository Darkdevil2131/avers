"""Bounded HTTP load/integrity check against a disposable database, never a public host.
Run with PYTHONPATH=. python scripts/load_check.py. No external research/inference.
"""
import concurrent.futures, json, os, secrets, socket, statistics, subprocess, sys, tempfile, time
from pathlib import Path
import httpx

USERS=30
ROUNDS=10

def main():
    credentials={f'load_user_{i}':secrets.token_urlsafe(32) for i in range(USERS)}
    samples=[];errors=[];projects=[];checks=0
    with tempfile.TemporaryDirectory(prefix='ares-load-') as temp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        database=os.environ.get('ARES_LOAD_DATABASE',str(Path(temp)/'load.db'))
        # Caller must supply a disposable PostgreSQL DB, never production.
        if database.startswith('postgres') and os.environ.get('ARES_LOAD_DISPOSABLE')!='yes':
            raise SystemExit('PostgreSQL load checks require ARES_LOAD_DISPOSABLE=yes')
        environment=dict(os.environ,ARES_DATABASE=database,ARES_CREDENTIALS=json.dumps(credentials),ARES_QUEUE_MODE='db',ARES_MODEL_CACHE=str(Path(temp)/'no-models'))
        environment.pop('ARES_REASONER_MODEL',None)
        url=f'http://127.0.0.1:{port}'
        with open(Path(temp)/'server.log','w+') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','ares.api:app_factory','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],env=environment,stdout=log,stderr=log)
            try:
                with httpx.Client(base_url=url,timeout=20) as client:
                    for _ in range(100):
                        if server.poll() is not None:raise RuntimeError('Server exited before readiness')
                        try:
                            if client.get('/health').status_code==200:break
                        except httpx.HTTPError:pass
                        time.sleep(.1)
                    else:raise RuntimeError('Readiness deadline exceeded')
                    for user,token in credentials.items():
                        headers={'Authorization':'Bearer '+token}
                        p=client.post('/projects',headers=headers,json={'name':user});p.raise_for_status()
                        pid=p.json()['id'];projects.append(pid)
                        response=client.post(f'/projects/{pid}/sources',headers=headers,json={'url':'https://example.org/'+user,'text':f'Private load fixture belonging to {user}. Humidity reduced coating stability.','license_status':'synthetic fixture'})
                        response.raise_for_status()
                def worker(index):
                    latencies=[];failures=[];verified=0
                    user=f'load_user_{index}'
                    with httpx.Client(base_url=url,headers={'Authorization':'Bearer '+credentials[user]},timeout=30) as client:
                        for round_id in range(ROUNDS):
                            for route,expected in [(f'/projects/{projects[index]}/sources',200),(f'/projects/{projects[(index+1)%USERS]}/sources',404)]:
                                start=time.perf_counter()
                                response=client.get(route)
                                latencies.append(time.perf_counter()-start)
                                if response.status_code!=expected:failures.append(f'{route}: expected {expected}, got {response.status_code}')
                                if expected==200 and (len(response.json())!=1 or user not in response.json()[0]['text']):failures.append('Source isolation/content mismatch')
                                verified+=1
                            key=f'load-{index}-{round_id}'
                            run_ids=[]
                            for _ in range(2):
                                start=time.perf_counter()
                                response=client.post(f'/projects/{projects[index]}/runs',headers={'Idempotency-Key':key},json={'question':'How does humidity affect coating stability?','external':False})
                                latencies.append(time.perf_counter()-start)
                                if response.status_code not in (200,201,202):failures.append(f'Run creation returned {response.status_code}')
                                run_ids.append(response.json().get('id'))
                            if not run_ids[0] or run_ids[0]!=run_ids[1]:failures.append('Idempotency failed')
                        response=client.get(f'/projects/{projects[index]}/runs')
                        if response.status_code!=200 or len(response.json())!=ROUNDS:failures.append('Persisted run count mismatch')
                    return latencies,failures,verified
                started=time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=USERS) as pool:
                    for result in pool.map(worker,range(USERS)):
                        samples.extend(result[0]);errors.extend(result[1]);checks+=result[2]
                elapsed=time.perf_counter()-started
            finally:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()
    ordered=sorted(samples)
    percentile=lambda p:ordered[min(len(ordered)-1,int((len(ordered)-1)*p))]
    summary={'scenario':'30 concurrent authenticated users, tenant reads/denials and idempotent queued writes',
        'database':'postgresql' if database.startswith('postgres') else 'sqlite','users':USERS,'rounds_per_user':ROUNDS,'timed_requests':len(samples),'isolation_responses_checked':checks,'expected_unique_runs':USERS*ROUNDS,
        'seconds':elapsed,'requests_per_second':len(samples)/elapsed,'latency_ms':{'p50':percentile(.5)*1000,'p95':percentile(.95)*1000,'p99':percentile(.99)*1000,'max':max(samples)*1000},
        'errors':errors,'passed':not errors,'limits':['Single HTTP API process on test host','No model inference, web collection, SSE soak or queue completion in this scenario','No uptime, deployment capacity or scientific reliability guarantee','30-user workload only; not an unlimited scale claim']}
    output=Path(os.environ.get('ARES_LOAD_OUTPUT','docs/load-check.json'));output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as out:out.write('```json\n'+json.dumps(summary,indent=2)+'\n```\n')
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
