"""Verify a running disposable Compose stack over HTTP, including real worker completion."""
import hashlib,json,os,time,urllib.request,urllib.error
TOKEN=json.loads(os.environ['ARES_CREDENTIALS'])['fixture']
BASE='http://127.0.0.1:8000'
def request(path,data=None,token=TOKEN):
    req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
for _ in range(90):
    try:
        if request('/health')['status']=='ok':break
    except (urllib.error.URLError,TimeoutError):time.sleep(1)
else:raise RuntimeError('Compose API did not become ready')
project=request('/projects',{'name':'Compose end-to-end fixture'})['id']
text='Humidity reduced coating stability by 20% in a controlled synthetic experiment. This is test data, not scientific evidence.'
source=request(f'/projects/{project}/sources',{'url':'https://example.org/compose-fixture','text':text,'license_status':'synthetic fixture'})
run=request(f'/projects/{project}/runs',{'question':'How does humidity affect coating stability?','external':False})['id']
for _ in range(90):
    state=request(f'/projects/{project}/runs/{run}')
    if state['status']=='completed':break
    if state['status']=='failed':raise RuntimeError('Worker failed to complete queued research')
    time.sleep(1)
else:raise RuntimeError('Worker completion deadline exceeded')
report=request(f'/projects/{project}/runs/{run}/report')
assert report['assessment']=='inconclusive' and report['calibrated'] is False
assert report['citations'] and report['findings']
for cite in report['citations']:
    assert cite['source_id']==source['id']
    assert cite['quote']==text[cite['start_offset']:cite['end_offset']]
    assert cite['digest']==hashlib.sha256(text.encode()).hexdigest()
assert report['reasoner']['status']=='unavailable',report['reasoner']
events=request(f'/projects/{project}/runs/{run}/events')
assert {'queued','plan','memory_retrieval','audit','report'}<={e['stage'] for e in events}
assert request(f'/projects/{project}/memory')[0]['status']=='pending'
try:request(f'/projects/{project}/sources',token=json.loads(os.environ['ARES_CREDENTIALS'])['outsider'])
except urllib.error.HTTPError as exc:assert exc.code==404
else:raise AssertionError('Cross-tenant read was allowed')
# Store identifiers for restart check; no secrets or source content.
with open('/tmp/ares-compose-check.json','w') as out:json.dump({'project':project,'run':run},out)
print('PASS: API -> PostgreSQL queue -> separate worker -> exact cited report -> pending memory; cross-tenant read denied; missing model explicitly disclosed')
