"""Live public API contract test. Logs provenance, never claims scientific validation."""
import base64,hashlib,json,os
from datetime import datetime,timezone
from ares.providers import EuropePMC
provider=EuropePMC();results=[]
for pmcid in ['PMC4383902','PMC5753258']:
    try:
        document=provider.fulltext(pmcid)
        metadata=document['document'];raw=base64.b64decode(metadata['original_xml_base64'])
        assert hashlib.sha256(raw).hexdigest()==metadata['original_sha256']
        assert len(document['text'])>1000
        for loc in metadata['locations']:assert document['text'][loc['start']:loc['end']]
        results.append({'pmcid':pmcid,'status':'passed','license':document['license_status'],'characters':len(document['text']),'locations':len(metadata['locations']),'original_sha256':metadata['original_sha256']})
    except Exception as exc:
        results.append({'pmcid':pmcid,'status':'failed','error':str(exc),'cause':str(exc.__cause__)[:200]})
record={'checked_at':datetime.now(timezone.utc).isoformat(),'checks':results,'passed':all(x['status']=='passed' for x in results)}
print(json.dumps(record,indent=2))
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:stream.write('## Live full-text contract\n```json\n'+json.dumps(record,indent=2)+'\n```\n')
if not record['passed']:raise SystemExit('Live full-text verification failed; do not mark complete')
