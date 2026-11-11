"""A bounded, keyless Europe PMC metadata adapter. No arbitrary URL fetch."""
import json
import re
from .documents import parse_jats
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


class ProviderError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        raise ProviderError("The source redirected the request")


class EuropePMC:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_request = 0.0
        self.cache = {}
        self.opener = urllib.request.build_opener(NoRedirect())

    def search(self, query, limit=8):
        key = (query, limit)
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 300:
                return cached[1]
            delay = 1.0 - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            params = urllib.parse.urlencode({"query": query, "format": "json",
                                              "pageSize": min(limit, 10), "resultType": "core"})
            request = urllib.request.Request(ENDPOINT + "?" + params, headers={"User-Agent": "ARES/0.2"})
            try:
                with self.opener.open(request, timeout=15) as response:
                    raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ProviderError("Source response exceeded the 2 MB budget")
                records = json.loads(raw)["resultList"]["result"]
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
                raise ProviderError("Europe PMC is unavailable or returned an invalid response") from exc
            results = []
            for record in records[:limit]:
                source_id = str(record.get("id", ""))
                source = str(record.get("source", "MED"))
                title = str(record.get("title", "")).strip()
                if not source_id or not title:
                    continue
                url = "https://europepmc.org/article/" + urllib.parse.quote(source, safe="") + "/" + urllib.parse.quote(source_id, safe="")
                # Only bibliographic metadata is stored automatically. Article rights vary.
                text = title + "\n" + str(record.get("authorString", "")) + "\n" + str(record.get("firstPublicationDate", ""))
                results.append({
                    "url": url, "title": title, "text": text[:100000],
                    "study_id": record.get("doi") or url,
                    "license_status": "bibliographic metadata; article rights require review",
                    "origin": "europepmc_metadata", "pmcid": record.get("pmcid"),
                    "is_open_access": record.get("isOpenAccess") == "Y",
                })
            self.cache[key] = (time.monotonic(), results)
            if len(self.cache) > 100:
                self.cache.pop(next(iter(self.cache)))
            return results

    def fulltext(self, pmcid):
        if not re.fullmatch(r"PMC[0-9]{1,12}",pmcid):
            raise ProviderError("Invalid PMC identifier")
        with self.lock:
            delay=1.0-(time.monotonic()-self.last_request)
            if delay>0:time.sleep(delay)
            self.last_request=time.monotonic()
            url="https://www.ebi.ac.uk/europepmc/webservices/rest/"+pmcid+"/fullTextXML"
            try:
                with self.opener.open(urllib.request.Request(url,headers={"User-Agent":"ARES/0.3"}),timeout=15) as response:
                    raw=response.read(4_000_001)
                return parse_jats(raw,pmcid)
            except Exception as exc:
                raise ProviderError("Full text unavailable, malformed, over budget, or license not permitted") from exc
