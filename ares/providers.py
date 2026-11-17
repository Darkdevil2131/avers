import json
import copy
import re
from .documents import DocumentIdentityError, DocumentLimitError, UnsupportedLicense, parse_jats,parse_bioc
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from defusedxml.common import DefusedXmlException

ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class ProviderError(Exception):
    def __init__(self, message, *, attempts=None):
        super().__init__(message)
        self.attempts = attempts or []


def fulltext_failure(provider, error):
    """Classify failures without exposing remote payloads or exception messages."""
    if isinstance(error, UnsupportedLicense):
        reason = 'unsupported_license'
    elif isinstance(error, DocumentIdentityError):
        reason = 'identity_mismatch'
    elif isinstance(error, DocumentLimitError):
        reason = 'content_limit'
    elif isinstance(error, urllib.error.HTTPError):
        if error.code == 404:
            reason = 'not_found'
        elif error.code == 429:
            reason = 'rate_limited'
        elif error.code in (401, 403):
            reason = 'access_denied'
        else:
            reason = 'http_error'
    elif isinstance(error, TimeoutError):
        reason = 'timeout'
    elif isinstance(error, urllib.error.URLError):
        reason = 'timeout' if isinstance(error.reason, TimeoutError) else 'network_error'
    elif isinstance(error, OSError):
        reason = 'network_error'
    elif isinstance(error, ProviderError):
        reason = 'redirect_blocked'
    elif isinstance(error, (ValueError, TypeError, KeyError, AttributeError, SyntaxError, DefusedXmlException)):
        reason = 'invalid_or_unreadable_content'
    else:
        reason = 'processing_error'
    return {'provider': provider, 'reason': reason}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ProviderError("The source redirected the request")


class EuropePMC:
    concurrent_fulltext = True
    def __init__(self):
        self.lock = threading.Lock()
        self.pacing_lock = threading.Lock()
        self.last_request = {'europe': 0.0, 'ncbi': 0.0}
        self.cache = {}
        self.opener = urllib.request.build_opener(NoRedirect())

    def pace_request(self, provider):
        # Serialize starts per provider, while allowing earlier requests to finish
        # independently. The collector bounds simultaneous document tasks.
        with self.pacing_lock:
            delay = 1.0 - (time.monotonic() - self.last_request[provider])
            if delay > 0:
                time.sleep(delay)
            self.last_request[provider] = time.monotonic()

    def search_titles(self, query):
        return self.search(query, require_titles=True)

    def search_with_provenance(self, query, limit=8):
        return self.search(query, limit, with_provenance=True)

    def search(self, query, limit=8, *, require_titles=False, with_provenance=False):
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ProviderError("Search query must contain 1–2000 characters")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ProviderError("Search limit must be an integer from 1 to 10")
        key = (query, limit)
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 300:
                records = copy.deepcopy(cached[1])
                return (records, {'provider': 'Europe PMC', 'fallback_used': False}) if with_provenance else records
            self.pace_request('europe')
            params = urllib.parse.urlencode({"query": query, "format": "json",
                                              "pageSize": min(limit, 10), "resultType": "core"})
            request = urllib.request.Request(ENDPOINT + "?" + params, headers={"User-Agent": "ARES/0.2"})
            try:
                with self.opener.open(request, timeout=15) as response:
                    raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ProviderError("Source response exceeded the 2 MB budget")
                records = json.loads(raw)["resultList"]["result"]
                if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
                    raise ValueError("Invalid search result structure")
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError, ProviderError) as exc:
                if require_titles:
                    raise ProviderError('Europe PMC title search is unavailable') from exc
                records = self.ncbi_search(query,limit)
                if with_provenance:
                    return records, {'provider': 'NCBI PMC', 'fallback_used': True,
                                     'primary_status': 'unavailable_or_invalid_response'}
                return records
            results = []
            for record in records[:limit]:
                source_id = str(record.get("id") or "")
                source = str(record.get("source") or "MED")
                title = record.get("title")
                if not isinstance(title, str):continue
                title = title.strip()
                if not source_id or not title:
                    continue
                url = "https://europepmc.org/article/" + urllib.parse.quote(source, safe="") + "/" + urllib.parse.quote(source_id, safe="")
                # Only bibliographic metadata is stored automatically. Article rights vary.
                text = title + "\n" + str(record.get("authorString", "")) + "\n" + str(record.get("firstPublicationDate", ""))
                results.append({
                    "url": url, "title": title, "text": text[:100000],
                    "study_id": record.get("doi") if isinstance(record.get("doi"),str) and record['doi'] else url,
                    "license_status": "bibliographic metadata; article rights require review",
                    "origin": "europepmc_metadata", "pmcid": record.get("pmcid") if isinstance(record.get("pmcid"),str) and re.fullmatch(r"PMC[0-9]{1,12}",record['pmcid']) else None,
                    "is_open_access": record.get("isOpenAccess") == "Y",
                })
            self.cache[key] = (time.monotonic(), copy.deepcopy(results))
            if len(self.cache) > 100:
                self.cache.pop(next(iter(self.cache)))
            return (results, {'provider': 'Europe PMC', 'fallback_used': False}) if with_provenance else results

    def fulltext(self, pmcid):
        if not isinstance(pmcid,str) or not re.fullmatch(r"PMC[0-9]{1,12}",pmcid):
            raise ProviderError("Invalid PMC identifier")
        self.pace_request('europe')
        url="https://www.ebi.ac.uk/europepmc/webservices/rest/"+pmcid+"/fullTextXML"
        try:
            with self.opener.open(urllib.request.Request(url,headers={"User-Agent":"ARES/0.3"}),timeout=15) as response:
                raw=response.read(4_000_001)
            return parse_jats(raw,pmcid)
        except Exception as primary:
            primary_attempt = fulltext_failure('Europe PMC', primary)
            # An independent approved public API, not an arbitrary webpage scraper.
            try:
                self.pace_request('ncbi')
                request=urllib.request.Request('https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/'+pmcid+'/unicode',headers={'User-Agent':'ARES/0.4'})
                with self.opener.open(request,timeout=20) as response:raw=response.read(4_000_001)
                result=parse_bioc(raw,pmcid)
                result['document']['primary_provider_error']=type(primary).__name__
                result['document']['fulltext_attempts'] = [primary_attempt, {'provider':'NCBI BioC','reason':'collected'}]
                return result
            except Exception as fallback:
                attempts = [primary_attempt, fulltext_failure('NCBI BioC', fallback)]
                raise ProviderError('Full text could not be collected from either provider.', attempts=attempts) from fallback

    def ncbi_search(self,query,limit):
        self.pace_request('ncbi')
        params=urllib.parse.urlencode({'db':'pmc','term':query+' AND open access[filter]','retmode':'json','retmax':min(limit,10)})
        try:
            request=urllib.request.Request('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?'+params,headers={'User-Agent':'ARES/0.4'})
            with self.opener.open(request,timeout=20) as response:raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError('Search response over budget')
            identifiers=json.loads(raw)['esearchresult']['idlist']
            if not isinstance(identifiers,list):raise ValueError('Invalid identifier list')
            return [{'pmcid':'PMC'+identifier,'is_open_access':True,'title':'Open-access candidate PMC'+identifier,
                     'text':'NCBI PMC search record '+identifier,'url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC'+identifier+'/',
                     'study_id':'PMC'+identifier,'license_status':'Bibliographic identifier; full-text license requires checking',
                     'origin':'ncbi_metadata'} for identifier in identifiers[:limit] if isinstance(identifier,str) and re.fullmatch(r'\d{1,12}',identifier)]
        except Exception as exc:raise ProviderError('Both metadata search APIs are unavailable') from exc
