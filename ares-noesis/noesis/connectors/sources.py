import re
import xml.etree.ElementTree as ET

from .base import BaseConnector, ConnectorUnavailable, Paper


_BLOCK_TAG = re.compile(r"</?(?:p|br|div|li|ul|ol|h[1-6]|tr|td|th|sec|title|jats:p|jats:title|jats:sec)\b[^>]*>", re.I)


def _strip_tags(s: str) -> str:
    """Remove markup. Block-level tags become a space (so paragraphs do not run together); inline tags (<b>, <i>, <sup>) are removed
    without adding a space, so "data</b>." stays "data." instead of "data ."."""
    s = _BLOCK_TAG.sub(" ", s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


class OpenAlexConnector(BaseConnector):
    name = "openalex"
    terms_url = "https://docs.openalex.org/"
    license_note = "Metadata CC0. Full-text only via listed open-access locations."
    min_interval = 0.15

    @staticmethod
    def _abstract(inv):
        if not inv:
            return ""
        pos = {i: w for w, idxs in inv.items() for i in idxs}
        return " ".join(pos[i] for i in sorted(pos))

    def search(self, query, limit=5, page=1):
        params = {"search": query, "per-page": limit, "page": page}
        if self.settings.contact_email:
            params["mailto"] = self.settings.contact_email
        data = self._get("https://api.openalex.org/works", params).json()
        out = []
        for w in data.get("results", []):
            loc = w.get("primary_location") or {}
            best = w.get("best_oa_location") or {}
            out.append(Paper(
                source=self.name, source_id=w.get("id", ""), title=w.get("display_name") or "",
                abstract=self._abstract(w.get("abstract_inverted_index")),
                doi=(w.get("doi") or "").replace("https://doi.org/", ""), year=w.get("publication_year"),
                authors=[a.get("author", {}).get("display_name", "") for a in w.get("authorships", [])],
                venue=((loc.get("source") or {}).get("display_name") or ""), url=w.get("id", ""),
                open_access_pdf=best.get("pdf_url") or "", license=best.get("license") or "",
                retracted=w.get("is_retracted"), is_preprint=(w.get("type") == "preprint"),
                cited_by=w.get("cited_by_count"), pub_types=[w.get("type") or ""]))
        return out


class CrossrefConnector(BaseConnector):
    name = "crossref"
    terms_url = "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"
    license_note = "Metadata is open; abstracts present only when publisher deposits them."
    min_interval = 0.2

    def search(self, query, limit=5, page=1):
        params = {"query": query, "rows": limit, "offset": (page - 1) * limit}
        if self.settings.contact_email:
            params["mailto"] = self.settings.contact_email
        data = self._get("https://api.crossref.org/works", params).json()
        out = []
        for it in data.get("message", {}).get("items", []):
            lic = (it.get("license") or [{}])[0].get("URL", "")
            out.append(Paper(
                source=self.name, source_id=it.get("DOI", ""), title=(it.get("title") or [""])[0],
                abstract=_strip_tags(it.get("abstract", "")), doi=it.get("DOI", ""),
                year=((it.get("issued") or {}).get("date-parts") or [[None]])[0][0],
                authors=[f"{a.get('given', '')} {a.get('family', '')}".strip() for a in it.get("author", [])],
                venue=(it.get("container-title") or [""])[0], url=it.get("URL", ""), license=lic,
                is_preprint=(it.get("type") == "posted-content"), cited_by=it.get("is-referenced-by-count"),
                pub_types=[it.get("type", "")]))
        return out


class ArxivConnector(BaseConnector):
    name = "arxiv"
    terms_url = "https://info.arxiv.org/help/api/tou.html"
    license_note = "Metadata free to use; per-paper licenses vary. All arXiv items are preprints (not peer reviewed)."
    min_interval = 3.0  # arXiv asks for >=3s between calls

    def search(self, query, limit=5, page=1):
        r = self._get("https://export.arxiv.org/api/query", {"search_query": f"all:{query}", "max_results": limit, "start": (page - 1) * limit})
        ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
        root = ET.fromstring(r.text)
        out = []
        for e in root.findall("a:entry", ns):
            pdf = ""
            for l in e.findall("a:link", ns):
                if l.get("title") == "pdf":
                    pdf = l.get("href", "")
            pub = e.findtext("a:published", "", ns)
            out.append(Paper(
                source=self.name, source_id=e.findtext("a:id", "", ns), title=" ".join(e.findtext("a:title", "", ns).split()),
                abstract=" ".join(e.findtext("a:summary", "", ns).split()), doi=e.findtext("x:doi", "", ns) or "",
                year=int(pub[:4]) if pub[:4].isdigit() else None,
                authors=[a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)],
                url=e.findtext("a:id", "", ns), open_access_pdf=pdf, license="arXiv (per-paper; check)",
                is_preprint=True, retracted=None, pub_types=["preprint"]))
        return out


class EuropePMCConnector(BaseConnector):
    name = "europepmc"
    terms_url = "https://europepmc.org/Help"
    license_note = "Metadata free. Full text only for open-access subset; check per-record license."
    min_interval = 0.2

    def search(self, query, limit=5, page=1):
        data = self._get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                         {"query": query, "format": "json", "pageSize": limit, "resultType": "core", "page": page}).json()
        out = []
        for it in data.get("resultList", {}).get("result", []):
            types = (it.get("pubTypeList") or {}).get("pubType", [])
            types = types if isinstance(types, list) else [types]
            out.append(Paper(
                source=self.name, source_id=f"{it.get('source', '')}:{it.get('id', '')}", title=it.get("title", ""),
                abstract=_strip_tags(it.get("abstractText", "")), doi=it.get("doi", "") or "",
                year=int(it["pubYear"]) if str(it.get("pubYear", "")).isdigit() else None,
                authors=[a.strip() for a in (it.get("authorString", "") or "").split(",") if a.strip()],
                venue=it.get("journalTitle", "") or "", url=f"https://europepmc.org/article/{it.get('source', '')}/{it.get('id', '')}",
                license=it.get("license", "") or "", retracted=any("Retracted" in t for t in types) or None,
                is_preprint=(it.get("source") == "PPR"), cited_by=it.get("citedByCount"), pub_types=types))
        return out


    def full_text(self, pmcid: str) -> list:
        """Open-access full text as [{section, text}] from Europe PMC (JATS XML). Raises ConnectorError (HTTP 404) when the article is not in the OA subset."""
        r = self._get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
        return parse_jats(r.text)


def parse_jats(xml_text: str) -> list:
    """Plain-text sections from JATS XML: one entry per top-level <sec> (title + paragraphs). Tables/figures/references are skipped."""
    root = ET.fromstring(xml_text)
    out = []
    body = root.find(".//body")
    if body is None:
        return out

    def text_of(el):
        return re.sub(r"\s+", " ", "".join(el.itertext())).strip()
    for sec in body.findall("sec"):
        title = text_of(sec.find("title")) if sec.find("title") is not None else ""
        paras = [text_of(p) for p in sec.iter("p")]
        if paras:
            out.append({"section": title.lower(), "text": " ".join(paras)})
    if not out:
        paras = [text_of(p) for p in body.iter("p")]
        if paras:
            out.append({"section": "", "text": " ".join(paras)})
    return out


class NIHReporterConnector(BaseConnector):
    name = "nih_reporter"
    terms_url = "https://api.reporter.nih.gov/"
    license_note = "US government data. Funded-project records only: they show what was funded, NOT that a claim is true. Never counted as evidence."
    min_interval = 1.0

    def search(self, query, limit=5, page=1):
        body = {"criteria": {"advanced_text_search": {"operator": "and", "search_field": "all", "search_text": query}},
                "offset": (page - 1) * limit, "limit": limit}
        data = self._post("https://api.reporter.nih.gov/v2/projects/search", body).json()
        out = []
        for it in data.get("results", []):
            out.append(Paper(
                source=self.name, source_id=str(it.get("appl_id", "")), title=it.get("project_title") or "", abstract=_strip_tags(it.get("abstract_text") or ""),
                year=it.get("fiscal_year"), authors=[p.get("full_name", "") for p in (it.get("principal_investigators") or [])],
                venue=(it.get("agency_ic_admin") or {}).get("name", "") if isinstance(it.get("agency_ic_admin"), dict) else "",
                url=it.get("project_detail_url") or "", license="US government work", pub_types=["grant"]))
        return out


class PatentsViewConnector(BaseConnector):
    name = "patentsview"
    terms_url = "https://patentsview.org/apis/purpose"
    license_note = "Requires a free API key (NOESIS_PATENTSVIEW_API_KEY). Patents describe claimed inventions, NOT verified science. Never counted as evidence."
    requires_auth = True
    min_interval = 1.5

    def available(self):
        ok, why = super().available()
        if ok and not self.settings.patentsview_api_key:
            return False, "no PatentsView API key configured"
        return ok, why

    def search(self, query, limit=5, page=1):
        import json
        params = {"q": json.dumps({"_text_any": {"patent_abstract": query}}),
                  "f": json.dumps(["patent_id", "patent_title", "patent_abstract", "patent_date", "inventors.inventor_name_first", "inventors.inventor_name_last"]),
                  "o": json.dumps({"size": limit, "page": page})}
        data = self._get("https://search.patentsview.org/api/v1/patent/", params, headers={"X-Api-Key": self.settings.patentsview_api_key}).json()
        out = []
        for it in data.get("patents", []):
            date = it.get("patent_date") or ""
            out.append(Paper(
                source=self.name, source_id=str(it.get("patent_id", "")), title=it.get("patent_title") or "", abstract=it.get("patent_abstract") or "",
                year=int(date[:4]) if date[:4].isdigit() else None,
                authors=[f"{i.get('inventor_name_first', '')} {i.get('inventor_name_last', '')}".strip() for i in (it.get("inventors") or [])],
                url=f"https://patents.google.com/patent/US{it.get('patent_id', '')}", license="US government data", pub_types=["patent"]))
        return out


class DataGovConnector(BaseConnector):
    name = "datagov"
    terms_url = "https://data.gov/terms/"
    license_note = "Dataset catalogue records. A listed dataset is not a finding. Never counted as evidence; license is per dataset."
    min_interval = 0.5

    def search(self, query, limit=5, page=1):
        data = self._get("https://catalog.data.gov/api/3/action/package_search", {"q": query, "rows": limit, "start": (page - 1) * limit}).json()
        out = []
        for it in (data.get("result") or {}).get("results", []):
            mod = it.get("metadata_modified") or ""
            out.append(Paper(
                source=self.name, source_id=it.get("id", ""), title=it.get("title") or "", abstract=_strip_tags(it.get("notes") or ""),
                year=int(mod[:4]) if mod[:4].isdigit() else None, authors=[(it.get("organization") or {}).get("title", "")] if it.get("organization") else [],
                url=f"https://catalog.data.gov/dataset/{it.get('name', '')}", license=it.get("license_title") or "", pub_types=["dataset"]))
        return out


class NasaAdsConnector(BaseConnector):
    name = "nasa_ads"
    terms_url = "https://ui.adsabs.harvard.edu/help/api/"
    license_note = "Requires free API token; metadata/abstracts only, rate-limited (5000 req/day default)."
    requires_auth = True
    min_interval = 0.3

    def available(self):
        ok, why = super().available()
        if ok and not self.settings.ads_token:
            return False, "NOESIS_ADS_TOKEN not configured"
        return ok, why

    def search(self, query, limit=5, page=1):
        data = self._get("https://api.adsabs.harvard.edu/v1/search/query",
                         {"q": query, "rows": limit, "start": (page - 1) * limit, "fl": "title,abstract,doi,year,author,pub,bibcode,citation_count,doctype"},
                         headers={"Authorization": f"Bearer {self.settings.ads_token}"}).json()
        out = []
        for d in data.get("response", {}).get("docs", []):
            out.append(Paper(
                source=self.name, source_id=d.get("bibcode", ""), title=(d.get("title") or [""])[0],
                abstract=d.get("abstract", "") or "", doi=(d.get("doi") or [""])[0], year=int(d["year"]) if d.get("year") else None,
                authors=d.get("author", []), venue=d.get("pub", ""), url=f"https://ui.adsabs.harvard.edu/abs/{d.get('bibcode', '')}",
                cited_by=d.get("citation_count"), is_preprint=(d.get("doctype") == "eprint"), pub_types=[d.get("doctype", "")]))
        return out


class PubMedConnector(BaseConnector):
    """NCBI E-utilities (esearch -> efetch). Free; NCBI asks for an API key for >3 req/s."""
    name = "pubmed"
    terms_url = "https://www.ncbi.nlm.nih.gov/books/NBK25497/"
    license_note = "Abstracts/metadata public; full text only via PMC open-access subset (not fetched here)."
    min_interval = 0.34

    def search(self, query, limit=5, page=1):
        key = {"api_key": self.settings.ncbi_api_key} if self.settings.ncbi_api_key else {}
        ids = self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                        {"db": "pubmed", "term": query, "retmax": limit, "retstart": (page - 1) * limit, "retmode": "json", **key}
                        ).json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        root = ET.fromstring(self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                                       {"db": "pubmed", "id": ",".join(ids), "retmode": "xml", **key}).text)
        out = []
        for art in root.findall(".//PubmedArticle"):
            mc = art.find("MedlineCitation")
            a = mc.find("Article")
            abstract = " ".join("".join(t.itertext()).strip() for t in a.findall("Abstract/AbstractText"))
            doi = next((i.text for i in art.findall(".//ArticleIdList/ArticleId") if i.get("IdType") == "doi"), "") or ""
            year = a.findtext("Journal/JournalIssue/PubDate/Year") or (a.findtext("Journal/JournalIssue/PubDate/MedlineDate") or "")[:4]
            types = [t.text for t in a.findall("PublicationTypeList/PublicationType") if t.text]
            pmid = mc.findtext("PMID", "")
            out.append(Paper(
                source=self.name, source_id=pmid, title="".join(a.find("ArticleTitle").itertext()).strip(), abstract=abstract, doi=doi,
                year=int(year) if str(year).isdigit() else None,
                authors=[f"{x.findtext('ForeName', '')} {x.findtext('LastName', '')}".strip() for x in a.findall("AuthorList/Author") if x.findtext("LastName")],
                venue=a.findtext("Journal/Title", ""), url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", pub_types=types,
                retracted=any("Retracted Publication" in t for t in types) or None, is_preprint=False))
        return out


class ClinicalTrialsConnector(BaseConnector):
    """ClinicalTrials.gov API v2. Registry records (design + enrollment are structured, so evidence design is exact).
    Only the first page is supported (the API pages by opaque token)."""
    name = "clinicaltrials"
    terms_url = "https://clinicaltrials.gov/about-site/terms-conditions"
    license_note = "US government data, public domain; cite NCT id."
    min_interval = 0.3

    def search(self, query, limit=5, page=1):
        if page > 1:
            return []
        data = self._get("https://clinicaltrials.gov/api/v2/studies", {"query.term": query, "pageSize": limit}).json()
        out = []
        for st in data.get("studies", []):
            ps = st.get("protocolSection", {})
            idm, dm = ps.get("identificationModule", {}), ps.get("designModule", {})
            nct = idm.get("nctId", "")
            randomized = (dm.get("designInfo") or {}).get("allocation") == "RANDOMIZED" and dm.get("studyType") == "INTERVENTIONAL"
            date = ((ps.get("statusModule") or {}).get("startDateStruct") or {}).get("date", "")
            out.append(Paper(
                source=self.name, source_id=nct, title=idm.get("officialTitle") or idm.get("briefTitle", ""),
                abstract=(ps.get("descriptionModule") or {}).get("briefSummary", ""), doi="", year=int(date[:4]) if date[:4].isdigit() else None,
                venue="ClinicalTrials.gov registry", url=f"https://clinicaltrials.gov/study/{nct}", license="public domain",
                pub_types=["Randomized Controlled Trial"] if randomized else ["Clinical Trial"],
                sample_size=(dm.get("enrollmentInfo") or {}).get("count"), is_preprint=False))
        return out


class SemanticScholarConnector(BaseConnector):
    name = "semanticscholar"
    terms_url = "https://www.semanticscholar.org/product/api/license"
    license_note = "API license restricts redistribution; metadata/abstracts for internal analysis. Unauthenticated limits are strict."
    min_interval = 1.1

    def search(self, query, limit=5, page=1):
        hd = {"x-api-key": self.settings.s2_api_key} if self.settings.s2_api_key else None
        data = self._get("https://api.semanticscholar.org/graph/v1/paper/search",
                         {"query": query, "limit": limit, "offset": (page - 1) * limit,
                          "fields": "title,abstract,year,authors,venue,externalIds,citationCount,openAccessPdf,publicationTypes"}, headers=hd).json()
        out = []
        for p in data.get("data", []):
            types = p.get("publicationTypes") or []
            out.append(Paper(
                source=self.name, source_id=p.get("paperId", ""), title=p.get("title") or "", abstract=p.get("abstract") or "",
                doi=(p.get("externalIds") or {}).get("DOI", "") or "", year=p.get("year"), authors=[a.get("name", "") for a in p.get("authors", [])],
                venue=p.get("venue") or "", url=f"https://www.semanticscholar.org/paper/{p.get('paperId', '')}",
                open_access_pdf=(p.get("openAccessPdf") or {}).get("url", ""), cited_by=p.get("citationCount"),
                pub_types=[t for t in types], is_preprint=False if types else False))
        return out


class COREConnector(BaseConnector):
    name = "core"
    terms_url = "https://core.ac.uk/services/api"
    license_note = "Requires a free API key (env NOESIS_CORE_API_KEY). Open-access aggregator; check each record's license."
    requires_auth = True
    min_interval = 1.0

    def available(self):
        ok, why = super().available()
        return (False, "NOESIS_CORE_API_KEY not configured") if ok and not self.settings.core_api_key else (ok, why)

    def search(self, query, limit=5, page=1):
        data = self._get("https://api.core.ac.uk/v3/search/works", {"q": query, "limit": limit, "offset": (page - 1) * limit},
                         headers={"Authorization": f"Bearer {self.settings.core_api_key}"}).json()
        out = []
        for w in data.get("results", []):
            lic = w.get("licenses") or []
            out.append(Paper(
                source=self.name, source_id=str(w.get("id", "")), title=w.get("title") or "", abstract=w.get("abstract") or "",
                doi=w.get("doi") or "", year=w.get("yearPublished"), authors=[a.get("name", "") for a in w.get("authors", [])],
                venue=w.get("publisher") or "", url=w.get("downloadUrl") or "", open_access_pdf=w.get("downloadUrl") or "",
                license=(lic[0].get("type", "") if lic and isinstance(lic[0], dict) else ""), pub_types=[w.get("documentType") or ""]))
        return out


class DOAJConnector(BaseConnector):
    name = "doaj"
    terms_url = "https://doaj.org/api/v3/docs"
    license_note = "Open-access journal articles; license type reported per journal."
    min_interval = 0.5

    def search(self, query, limit=5, page=1):
        from urllib.parse import quote
        data = self._get(f"https://doaj.org/api/search/articles/{quote(query, safe='')}", {"page": page, "pageSize": limit}).json()
        out = []
        for r in data.get("results", []):
            b = r.get("bibjson", {})
            doi = next((i.get("id", "") for i in b.get("identifier", []) if i.get("type") == "doi"), "")
            lic = ((b.get("journal") or {}).get("license") or [{}])[0].get("type", "")
            out.append(Paper(
                source=self.name, source_id=r.get("id", ""), title=b.get("title", ""), abstract=b.get("abstract", ""), doi=doi,
                year=int(b["year"]) if str(b.get("year", "")).isdigit() else None, authors=[a.get("name", "") for a in b.get("author", [])],
                venue=(b.get("journal") or {}).get("title", ""), url=(b.get("link") or [{}])[0].get("url", ""), license=lic))
        return out


class GitHubConnector(BaseConnector):
    """Finds public implementations/datasets (NOT literature). Used by the Technology agent's find_implementations operation."""
    name = "github"
    terms_url = "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service"
    license_note = "Repository metadata only; each repo has its own license (reported as SPDX id)."
    min_interval = 2.0

    def search(self, query, limit=5, page=1):
        hd = {"Authorization": f"Bearer {self.settings.github_token}"} if self.settings.github_token else None
        data = self._get("https://api.github.com/search/repositories", {"q": query, "per_page": limit, "page": page, "sort": "stars"}, headers=hd).json()
        return [Paper(source=self.name, source_id=r.get("full_name", ""), title=r.get("full_name", ""), abstract=r.get("description") or "",
                      url=r.get("html_url", ""), license=((r.get("license") or {}).get("spdx_id") or ""), cited_by=r.get("stargazers_count"),
                      pub_types=["software"]) for r in data.get("items", [])]


def default_connectors(settings=None) -> dict:
    cs = [OpenAlexConnector, CrossrefConnector, ArxivConnector, EuropePMCConnector, NasaAdsConnector, PubMedConnector,
          ClinicalTrialsConnector, SemanticScholarConnector, COREConnector, DOAJConnector, GitHubConnector,
          NIHReporterConnector, PatentsViewConnector, DataGovConnector]
    return {c.name: c(settings) for c in cs}
