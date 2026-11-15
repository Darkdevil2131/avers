"""Canonicalize known identifiers. A shared identifier does not prove independence."""

import re
from urllib.parse import unquote

DOI = re.compile(r'(?:doi:\s*)?(10\.\d{4,9}/\S+)', re.I)
DOI_URL = re.compile(r'https?://(?:dx\.)?doi\.org/([^?#]+)(?:[?#].*)?', re.I)
PMC_URL = re.compile(
    r'https?://(?:(?:www\.)?europepmc\.org/(?:articles/|article/PMC/)'
    r'|pmc\.ncbi\.nlm\.nih\.gov/articles/|www\.ncbi\.nlm\.nih\.gov/pmc/articles/)'
    r'(PMC\d{1,12})/?(?:[?#].*)?', re.I,
)
REGISTRY_ID = re.compile(r'PMC\d{1,12}|NCT\d{8}', re.I)


def study_identifier(value):
    value = value.strip()
    resolver = DOI_URL.fullmatch(value)
    doi = DOI.fullmatch(unquote(resolver[1]) if resolver else value)
    if doi:
        return doi[1].casefold()
    pmc = PMC_URL.fullmatch(value)
    if pmc:
        return pmc[1].upper()
    if REGISTRY_ID.fullmatch(value):
        return value.upper()
    return value
