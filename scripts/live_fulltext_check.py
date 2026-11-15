"""Live public API contract test. Logs provenance, never claims scientific validation."""
import base64,hashlib,json,os
from datetime import datetime,timezone
from ares.providers import EuropePMC,ProviderError
provider=EuropePMC();results=[]
topic_query = '"humidity" AND "coating" AND "stability"'
try:
    titles = provider.search_titles(topic_query)
    assert titles and all(item['origin'] == 'europepmc_metadata' and item['title'] for item in titles)
    results.append({'scope': 'prior-art title search', 'status': 'passed', 'titles': len(titles), 'query': topic_query})
except Exception as exc:
    results.append({'scope': 'prior-art title search', 'status': 'failed', 'error': str(exc), 'cause': str(exc.__cause__)[:200]})
for pmcid in ['PMC4383902','PMC5753258','PMC13676768']:
    try:
        document=provider.fulltext(pmcid)
        metadata=document['document'];raw=base64.b64decode(metadata.get('original_xml_base64') or metadata['original_content_base64'])
        assert hashlib.sha256(raw).hexdigest()==metadata['original_sha256']
        assert len(document['text'])>1000
        for loc in metadata['locations']:assert document['text'][loc['start']:loc['end']]
        assert metadata['identity_status'] in {'matched', 'not_reported'}
        results.append({'pmcid':pmcid,'status':'passed','provider':document['origin'],'license':document['license_status'],'identity_status':metadata['identity_status'],'characters':len(document['text']),'locations':len(metadata['locations']),'original_sha256':metadata['original_sha256']})
    except Exception as exc:
        failure = {'pmcid':pmcid,'status':'failed','error_type':type(exc).__name__}
        if isinstance(exc, ProviderError):
            failure['attempts'] = exc.attempts
        results.append(failure)
record={'checked_at':datetime.now(timezone.utc).isoformat(),'checks':results,'passed':all(x['status']=='passed' for x in results)}
print(json.dumps(record,indent=2))
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as stream:stream.write('## Live full-text contract\n```json\n'+json.dumps(record,indent=2)+'\n```\n')
if not record['passed']:raise SystemExit('Live full-text verification failed; do not mark complete')
