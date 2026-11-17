"""Bounded collection and evidence-triggered follow-up planning."""

import re

from .providers import ProviderError
from .study_identifiers import study_identifier

MAX_SEARCHES = 2


def evidence_signals(findings, citations, criticism):
    """Counts describe retrieval coverage, never study quality or independence."""
    by_label = {citation['label']: citation for citation in citations}
    studies = {
        study_identifier(by_label[finding['citation']]['study_id'])
        for finding in findings if by_label[finding['citation']].get('study_id')
    }
    pairs = criticism['potential_disagreements']
    routes = {'context_mismatch': 0, 'shared_study': 0, 'review_conflict': 0, 'unresolved': 0}
    for pair in pairs:
        state = pair.get('reviewed_context', {}).get('state')
        if pair.get('same_study_identifier'):
            routes['shared_study'] += 1
        elif state == 'review-conflict':
            routes['review_conflict'] += 1
        elif state == 'context-mismatched' or any(
            condition['state'] == 'differs' for condition in pair.get('reported_exposure_comparison', [])
        ):
            routes['context_mismatch'] += 1
        else:
            routes['unresolved'] += 1
    return {
        'candidate_findings': len(findings),
        'candidate_study_ids': len(studies),
        'potential_disagreements': len(pairs),
        'disagreement_routes': routes,
    }


def question_keywords(question):
    """Return a small, ordered list of literal tokens from the submitted question."""
    ignored = {'what', 'does', 'show', 'about', 'how', 'why', 'when', 'which', 'where',
               'the', 'and', 'with', 'from', 'under', 'effect', 'affect', 'evidence', 'this'}
    return list(dict.fromkeys(
        word.casefold() for word in re.findall(r'[^\W\d_]{3,}', question)
        if len(word) <= 80 and word.casefold() not in ignored
    ))[:5]


def follow_up(question, signals):
    # Only the question is approved for external search. Private findings inform
    # the decision but their contents never enter the generated query.
    tokens = question_keywords(question)
    if not tokens:
        return None
    base = ' AND '.join(f'"{word}"' for word in tokens)
    routes = signals['disagreement_routes']
    if routes['unresolved']:
        return ('counterevidence', base + ' AND (replication OR "no effect" OR disagreement OR comparison)',
                'The first retrieval flagged opposing findings without a known shared study identifier or documented context mismatch.')
    if routes['context_mismatch']:
        return ('compare_study_conditions', base + ' AND ("test conditions" OR protocol OR "study design")',
                'Opposing findings differ in reviewed context or explicitly reported conditions. Search for methods and comparable evidence.')
    if signals['candidate_study_ids'] < 2:
        return ('broaden_search', ' OR '.join(f'"{word}"' for word in tokens),
                'The first retrieval found candidates from fewer than two study identifiers.')
    return None


class EvidenceCollector:
    """At most two searches and four full-text attempts across both rounds."""

    def __init__(self, provider, store_sources, event, stopped, requested):
        self.provider = provider
        self.store_sources = store_sources
        self.event = event
        self.stopped = stopped
        self.audit = {
            'requested': requested, 'status': 'not_requested', 'queries': [],
            'metadata_records': 0, 'fulltext_attempted': 0, 'fulltext_stored': 0,
            'errors': [], 'fallbacks': [], 'identity_unverified': [], 'bounded': False,
            'scope': 'Bounded literature collection; absence of results is not evidence against a hypothesis.',
        }
        self.urls = set()
        self.records = []
        self.seen = set()
        self.references = []

    def collect(self, strategy, query, reason, fetch_limit):
        if self.stopped():
            self.audit['bounded'] = True
            return
        self.event('planner_decision', {'strategy': strategy, 'query': query, 'reason': reason})
        entry = {'query': query, 'strategy': strategy, 'reason': reason}
        self.audit['queries'].append(entry)
        search_succeeded = True
        try:
            search_with_provenance = getattr(self.provider, 'search_with_provenance', None)
            if callable(search_with_provenance):
                found, provenance = search_with_provenance(query)
                records = list(found)
                entry.update(provenance)
            else:
                records = list(self.provider.search(query))
        except ProviderError as exc:
            search_succeeded = False
            message = str(exc)[:300]
            stage = 'search' if strategy == 'primary_evidence' else strategy
            self.audit['errors'].append({'stage': stage, 'message': message})
            self.event('external_search_failed', {'message': message, 'strategy': strategy})
            # References from the first round remain eligible after search failure.
            records = []
        if self.stopped():
            self.audit['bounded'] = True
            return
        fresh = []
        for record in records:
            if record['url'] not in self.urls:
                self.urls.add(record['url'])
                fresh.append(record)
        if fresh:
            self.store_sources(fresh)
            self.records.extend(fresh)
        self.audit['metadata_records'] = len(self.urls)
        if search_succeeded:
            self.event('external_search_completed', {'provider': entry.get('provider', 'not recorded'), 'count': len(fresh),
                                                     'content': 'metadata', 'strategy': strategy})
        roots = list(dict.fromkeys(
            record['pmcid'] for record in records if record.get('is_open_access') and record.get('pmcid')
            and record['pmcid'] not in self.seen
        ))
        if len(roots) > 2:
            self.audit['bounded'] = True
        if not callable(getattr(self.provider, 'fulltext', None)):
            return
        frontier = [(pmcid, 0) for pmcid in roots[:2]] + self.references
        self.references = []
        self.fetch(frontier, fetch_limit)

    def fetch(self, frontier, limit):
        while frontier and len(self.seen) < limit and not self.stopped():
            pmcid, depth = frontier.pop(0)
            if pmcid in self.seen:
                continue
            self.seen.add(pmcid)
            self.audit['fulltext_attempted'] += 1
            self.event('spider_fetch', {'pmcid': pmcid, 'depth': depth, 'source': 'Europe PMC open-access API'})
            try:
                document = self.provider.fulltext(pmcid)
            except ProviderError as exc:
                message = str(exc)[:300]
                details = {'pmcid': pmcid, 'message': message}
                if exc.attempts:
                    details['attempts'] = exc.attempts
                self.audit['errors'].append({'stage': 'fulltext', **details})
                self.event('document_rejected', details)
                continue
            if self.stopped():
                self.audit['bounded'] = True
                break
            source_id, = self.store_sources([document])
            self.audit['fulltext_stored'] += 1
            details = {'source_id': source_id, 'pmcid': pmcid,
                       'characters': len(document['text']), 'license': document['license_status']}
            metadata = document.get('document', {})
            identity = metadata.get('identity_status')
            if identity:
                details['identity_status'] = identity
            if identity == 'not_reported':
                self.audit['identity_unverified'].append({'pmcid': pmcid, 'source_id': source_id})
            attempts = metadata.get('fulltext_attempts')
            if attempts:
                details['attempts'] = attempts
                self.audit['fallbacks'].append({'pmcid': pmcid, 'source_id': source_id, 'attempts': attempts})
            self.event('document_ingested', details)
            if depth == 0:
                frontier.extend((ref, 1) for ref in document['document']['references'][:2]
                                if ref not in self.seen)
        self.references = [(pmcid, depth) for pmcid, depth in frontier if pmcid not in self.seen]

    def finish(self):
        if self.references:
            self.audit['bounded'] = True
        if self.audit['errors'] or self.audit['bounded']:
            status = 'partial' if self.audit['metadata_records'] or self.audit['fulltext_stored'] else 'unavailable'
        elif self.audit['fulltext_stored']:
            status = 'collected'
        else:
            status = 'metadata_only' if self.audit['metadata_records'] else 'no_results'
        self.audit['status'] = status
        self.event('collection_summary', self.audit)
