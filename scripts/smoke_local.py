"""End-to-end synthetic RAG/model check; requires explicitly prepared local models."""
import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from ares.api import create_app
with tempfile.TemporaryDirectory() as directory:
    client=TestClient(create_app(Path(directory)/'db',{'test':'x'*40}),headers={'Authorization':'Bearer '+'x'*40})
    project=client.post('/projects',json={'name':'Synthetic integration smoke'}).json()['id']
    text='Synthetic observation: Coating adhesion decreased after exposure to high humidity. Water uptake was measured before the adhesion test.'
    client.post(f'/projects/{project}/sources',json={'url':'https://example.org/synthetic','title':'Synthetic coating observation','license_status':'synthetic test fixture','text':text})
    run=client.post(f'/projects/{project}/runs',json={'question':'How might humidity affect coating adhesion?'}).json()['id']
    report=client.get(f'/projects/{project}/runs/{run}/report').json()
    assert report['retrieval']['mode']=='hybrid'
    assert report['reasoner']['status']=='completed',report['reasoner']
    if report['reasoner'].get('answer'):assert report['reasoner']['answer'] in text
    for finding in report['findings']:assert text[finding['start_offset']:finding['end_offset']]==finding['statement']
    print(json.dumps({'dataset':'Synthetic integration example; not scientific validation','report':report},indent=2))
