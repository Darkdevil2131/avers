import io
import json
import pytest
from ares.providers import EuropePMC, ProviderError
from test_research import client, project, run, source, FixtureProvider
from fastapi.testclient import TestClient


class Opener:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
    def open(self, *args, **kwargs):
        self.calls += 1
        return io.BytesIO(json.dumps(self.payload).encode())


@pytest.mark.parametrize('records', [None, {}, ['invalid'], 42])
def test_bad_search_schema_uses_approved_fallback(monkeypatch, records):
    provider = EuropePMC()
    provider.opener = Opener({'resultList': {'result': records}})
    calls = []
    monkeypatch.setattr(provider, 'ncbi_search', lambda q, n: calls.append((q,n)) or [])
    assert provider.search('coating') == []
    assert calls == [('coating',8)]


def test_cached_results_are_not_mutated_by_broadened_search():
    provider = EuropePMC()
    provider.opener = Opener({'resultList': {'result': [
        {'id':'1','title':'Coating paper','pmcid': {'invalid':True},'doi':[]},
        {'id':'2','title':None}]}})
    first = provider.search('coating')
    assert len(first) == 1 and first[0]['pmcid'] is None
    assert first[0]['study_id'] == first[0]['url']
    first[0]['title'] = 'tampered'
    first.append({'title':'unrelated'})
    again = provider.search('coating')
    assert len(again) == 1 and again[0]['title'] == 'Coating paper'
    assert provider.opener.calls == 1


@pytest.mark.parametrize('query,limit', [('',8), ('x',0), ('x',11), ('x',True), (None,8)])
def test_invalid_search_input_does_not_make_requests(query, limit):
    provider = EuropePMC()
    provider.opener = Opener({})
    with pytest.raises(ProviderError):provider.search(query,limit)
    assert provider.opener.calls == 0


def test_collection_failure_is_saved_in_report_and_export(tmp_path):
    c = client(tmp_path,provider=FixtureProvider(fail=True))
    pid = project(c);source(c,pid)
    rid = run(c,pid,external=True)
    report = c.get(f'/projects/{pid}/runs/{rid}/report').json()
    assert report['collection']['status'] == 'unavailable'
    assert report['collection']['errors'][0]['stage'] == 'search'
    assert report['citations'] and report['assessment'] == 'inconclusive'
    assert 'Status: unavailable' in report['markdown']


def test_broader_failure_preserves_first_search_and_fulltext(tmp_path):
    class Partial:
        def __init__(self):self.calls=0
        def search(self,query):
            self.calls+=1
            if self.calls==2:raise ProviderError('Broader search unavailable')
            return [{'url':'https://example.org/metadata','title':'Humidity coating','text':'Humidity coating metadata',
                     'license_status':'fixture','origin':'fixture_metadata','is_open_access':True,'pmcid':'PMC1'}]
        def fulltext(self,pmcid):
            return {'url':'https://example.org/fulltext','title':'Humidity coating','text':'Humidity reduced coating stability in this synthetic fixture.',
                    'license_status':'fixture','origin':'fixture_fulltext','document':{'references':[]}}
    c=client(tmp_path,provider=Partial());pid=project(c);rid=run(c,pid,external=True)
    report=c.get(f'/projects/{pid}/runs/{rid}/report').json()
    audit=report['collection']
    assert audit['status']=='partial'
    assert audit['metadata_records']==audit['fulltext_attempted']==audit['fulltext_stored']==1
    assert len(audit['queries'])==2 and report['citations']


def test_no_results_is_distinct_from_not_requested(tmp_path):
    class Empty:
        def search(self,query):return []
    c=client(tmp_path,provider=Empty());pid=project(c)
    for external,expected in [(True,'no_results'),(False,'not_requested')]:
        rid=run(c,pid,external=external)
        report=c.get(f'/projects/{pid}/runs/{rid}/report').json()
        assert report['collection']['status']==expected
        assert report['assessment']=='inconclusive'


@pytest.mark.parametrize('fulltext_allowed', [False, True])
def test_metadata_deduplication_and_rejected_fulltext_are_disclosed(tmp_path, fulltext_allowed):
    class Metadata:
        def search(self,query):
            return [{'url':'https://example.org/metadata','title':'Humidity metadata','text':'Humidity metadata',
                     'license_status':'fixture','origin':'fixture_metadata','is_open_access':fulltext_allowed,'pmcid':'PMC2'}]
        def fulltext(self,pmcid):raise ProviderError('Unsupported full-text license')
    c=client(tmp_path,provider=Metadata());pid=project(c);rid=run(c,pid,external=True)
    report=c.get(f'/projects/{pid}/runs/{rid}/report').json()
    audit=report['collection']
    assert audit['metadata_records']==1  # Same record from both queries is counted once.
    assert audit['fulltext_stored']==0
    assert audit['status']==('partial' if fulltext_allowed else 'metadata_only')
    assert report['findings']==[]  # Bibliographic titles are not scientific findings.
    if fulltext_allowed:
        assert audit['errors'][0]['message']=='Unsupported full-text license'
        assert 'Unsupported full-text license' in report['markdown']


@pytest.mark.parametrize('opposing,expected_strategy', [(False, 'broaden_search'), (True, 'counterevidence')])
def test_follow_up_uses_retrieved_evidence_and_keeps_request_budget(
    tmp_path, monkeypatch, opposing, expected_strategy,
):
    class Provider:
        def __init__(self):
            self.queries = []
            self.fetches = []

        def search(self, query):
            self.queries.append(query)
            # Two hits in round one even when only one study has usable full text.
            ids = ['PMC1', 'PMC2'] if len(self.queries) == 1 else ['PMC3', 'PMC4', 'PMC5']
            return [{'url': f'https://example.org/metadata/{pmcid}', 'title': f'Record {pmcid}',
                     'text': 'Humidity coating stability metadata', 'license_status': 'fixture',
                     'origin': 'fixture_metadata', 'is_open_access': True, 'pmcid': pmcid}
                    for pmcid in ids]

        def fulltext(self, pmcid):
            self.fetches.append(pmcid)
            if pmcid == 'PMC99' or (pmcid == 'PMC2' and not opposing):
                raise ProviderError('No permitted full text')
            direction = {'PMC1': 'increased', 'PMC2': 'decreased', 'PMC3': 'decreased', 'PMC4': 'increased'}[pmcid]
            return {'url': f'https://example.org/fulltext/{pmcid}', 'title': f'Study {pmcid}',
                    'text': f'Humidity {direction} coating stability during the controlled test.',
                    'license_status': 'Synthetic fixture', 'study_id': pmcid,
                    'origin': 'fixture_fulltext', 'document': {'references': ['PMC99']}}

    provider = Provider()
    api = client(tmp_path, provider=provider)
    pid = project(api)
    rid = run(api, pid, external=True)
    route = f'/projects/{pid}/runs/{rid}/report'
    report = api.get(route).json()
    audit = report['collection']
    assert len(provider.queries) == 2
    assert provider.fetches == ['PMC1', 'PMC2', 'PMC3', 'PMC4']
    assert audit['fulltext_attempted'] == 4 and audit['bounded']
    assert audit['queries'][1]['strategy'] == expected_strategy
    assert audit['adaptation']['decision'] == expected_strategy
    assert audit['adaptation']['before']['candidate_study_ids'] == (2 if opposing else 1)
    if opposing:
        assert 'replication' in provider.queries[1]
        assert audit['adaptation']['before']['potential_disagreements'] == 1
    else:
        assert audit['adaptation']['after']['candidate_study_ids'] > audit['adaptation']['before']['candidate_study_ids']
    assert report['assessment'] == 'inconclusive'
    assert f'Follow-up decision: {expected_strategy}' in report['markdown']
    exported = api.get(route + '.json')
    assert exported.json() == report
    assert exported.headers['content-disposition'] == 'attachment; filename="ares-report.json"'
    outsider = TestClient(api.app, headers={'Authorization': 'Bearer ' + 'b' * 40})
    assert outsider.get(route + '.json').status_code == 404
    if not opposing:
        import ares.research as research
        monkeypatch.setattr(research, 'follow_up', lambda question, signals: None)
        baseline_dir = tmp_path / 'static'
        baseline_dir.mkdir()
        baseline_provider = Provider()
        baseline = client(baseline_dir, provider=baseline_provider)
        baseline_pid = project(baseline)
        baseline_rid = run(baseline, baseline_pid, external=True)
        baseline_report = baseline.get(f'/projects/{baseline_pid}/runs/{baseline_rid}/report').json()
        assert len(baseline_provider.queries) == 1
        assert baseline_report['collection']['adaptation']['after']['candidate_study_ids'] < (
            audit['adaptation']['after']['candidate_study_ids']
        )
