"""Bounded topic search and local screening of literature titles."""

import re

from .agents import terms
from .collection import MAX_SEARCHES, question_keywords
from .providers import ProviderError

GENERIC = set('changing reported measured response otherwise matched conditions may change test testable study proposal effect'.split())


def search_prior_art(question, collection, provider, stopped, event):
    """Use at most the remaining search slot. Send only question keywords."""
    result = {'status': 'not_requested', 'query': None, 'records': 0}
    if not collection['requested']:
        return result, []
    if len(collection['queries']) >= MAX_SEARCHES or stopped():
        return {**result, 'status': 'budget_exhausted'}, []
    keywords = question_keywords(question)[:3]
    if len(keywords) < 2:
        return {**result, 'status': 'insufficient_query_terms'}, []
    query = ' AND '.join(f'"{word}"' for word in keywords)
    result['query'] = query
    if any(entry['query'] == query for entry in collection['queries']):
        return {**result, 'status': 'already_searched'}, []
    collection['queries'].append({
        'query': query, 'strategy': 'prior_art',
        'reason': 'Use the remaining search slot to check related literature titles.',
    })
    event('external_search_started', {'provider': 'Europe PMC', 'strategy': 'prior_art'})
    try:
        search = getattr(provider, 'search_titles', provider.search)
        records = list(search(query))
    except ProviderError:
        event('external_search_failed', {'strategy': 'prior_art', 'message': 'Literature title search unavailable.'})
        return {**result, 'status': 'unavailable'}, []
    titles = [record for record in records if record.get('origin') != 'ncbi_metadata']
    status = 'completed' if len(titles) == len(records) else 'titles_unavailable'
    event('external_search_completed', {'strategy': 'prior_art', 'count': len(titles), 'content': 'titles', 'status': status})
    return {**result, 'status': status, 'records': len(titles)}, titles


def screen_prior_art(proposal, question, citations, records, collection, search=None):
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
    if not matches and (collection['status'] in {'not_requested', 'unavailable', 'partial'}
                        or (search and search['status'] != 'completed')):
        status = 'screen_incomplete'
    return {
        'status': status,
        'matches': matches,
        'scope': 'Title overlap among retrieved project passages and records returned by this run’s literature searches.',
        'collection_status': collection['status'],
        'topic_search': search or {'status': 'not_recorded'},
        'novelty_verified': False,
    }


def _identity(value):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', value.strip(), flags=re.I).casefold()
