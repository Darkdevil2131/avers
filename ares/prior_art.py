"""Screen retrieved literature titles for possible overlap with a proposal."""

import re

from .agents import terms

GENERIC = set('changing reported measured response otherwise matched conditions may change test testable study proposal effect'.split())


def screen_prior_art(proposal, question, citations, records, collection):
    # Compare proposal wording locally. No private citation or hypothesis is sent
    # to the literature provider by this screening stage.
    objective = terms(question) - GENERIC
    candidate = terms(proposal['statement']) - GENERIC
    if proposal['kind'] != 'model_generated_candidate':
        candidate |= objective
    anchors = {proposal.get('source_id')} | {
        ref['source_id'] for ref in proposal.get('evidence_refs', [])
    }
    anchors.discard(None)
    anchor_ids = {citation['study_id'] for citation in citations
                  if citation['source_id'] in anchors and citation.get('study_id')}
    anchor_ids = {_identity(item) for item in anchor_ids}
    by_identity = {}
    for record in [*citations, *records]:
        identity = _identity(record.get('study_id') or record['url'])
        title_terms = terms(record['title']) - GENERIC
        overlap = title_terms & candidate
        if identity in anchor_ids or record.get('source_id') in anchors or len(overlap) < 2:
            continue
        score = (len(overlap & objective), len(overlap))
        match = {'title': record['title'], 'url': record['url'], 'matched_terms': sorted(overlap)}
        previous = by_identity.get(identity)
        if previous is None or score > previous[0]:
            by_identity[identity] = (score, match)
    ranked = sorted(by_identity.values(), key=lambda item: (-item[0][0], -item[0][1], item[1]['title']))
    matches = [entry[1] for entry in ranked[:5]]
    status = 'possible_overlap' if matches else 'no_title_overlap_found'
    if not matches and collection['status'] in {'not_requested', 'unavailable', 'partial'}:
        status = 'screen_incomplete'
    return {
        'status': status,
        'matches': matches,
        'scope': 'Title overlap among retrieved project passages and records returned by this run’s literature searches.',
        'collection_status': collection['status'],
        'novelty_verified': False,
    }


def _identity(value):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value.strip(), flags=re.I).casefold()
