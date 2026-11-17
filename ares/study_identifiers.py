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



def evidence_identity(record):
    return study_identifier(record.get('study_id') or record.get('url') or record['source_id'])


def diversify_evidence(ranked, limit, *, identity=evidence_identity):
    """Preserve the best-ranked result and prefer different substantive sources."""
    first, remaining, metadata = [], [], []
    study_ids, digests = set(), set()
    for record in ranked:
        if record.get('origin', '').endswith('_metadata'):
            metadata.append(record)
            continue
        study = identity(record)
        digest = record.get('digest')
        if study in study_ids or digest and digest in digests:
            remaining.append(record)
        else:
            first.append(record)
        study_ids.add(study)
        if digest:
            digests.add(digest)
    return (first + remaining + metadata)[:limit]


def compare_evidence(findings, citations, question=''):
    # Apply the point-value requirement only to explicit requests for both
    # conditions. General questions about their effects use normal selection.
    asks_conditions = re.match(
        r'^\s*(?:what|which) (?:(?P<stage>conditioning|exposure|testing|test) )?'
        r'temperatures? and relative humidity(?: levels?)? (?:was|were) used\b',
        question, re.I,
    )
    required = ('temperature', 'relative_humidity') if asks_conditions else ()
    stage = asks_conditions.group('stage') if asks_conditions else None
    if stage:
        stage = stage.casefold()
        if stage == 'test':
            stage = 'testing'
    by_label = {citation['label']: citation for citation in citations}
    observations, seen_studies, seen_digests = [], set(), set()
    for finding in findings:
        values = finding.get('reported_exposure', {})
        if any(field not in values or (stage and values[field]['stage'] != stage) for field in required):
            continue
        citation = by_label[finding['citation']]
        study = evidence_identity(citation)
        digest = citation.get('digest')
        if study in seen_studies or digest and digest in seen_digests:
            continue
        seen_studies.add(study)
        if digest:
            seen_digests.add(digest)
        observations.append({
            'citation': finding['citation'], 'source_id': finding['source_id'],
            'title': citation.get('title') or citation['url'],
            'study_identifier': study, 'quote': finding['statement'],
            'start_offset': finding['start_offset'], 'end_offset': finding['end_offset'],
        })
    status = ('multiple_source_candidates' if len(observations) >= 2 else
              'single_source_candidate' if observations else 'no_extracted_evidence')
    scope = 'Candidate observations for comparison. Study independence and scientific support require review.'
    if required:
        stage_label = f' for {stage}' if stage else ''
        scope = f'This answer requires explicit temperature and relative humidity values{stage_label}. {scope}'
    return {'status': status, 'study_identifiers': len(observations), 'observations': observations,
            'scope': scope, 'required_conditions': list(required), 'required_stage': stage}
