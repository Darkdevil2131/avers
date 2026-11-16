"""Paired software checks with a fixed search budget and synthetic study snapshots."""
import pytest

from test_research import client, project, run


class SnapshotProvider:
    def __init__(self, first_pair):
        self.first_pair = first_pair
        self.queries = []
        self.fetches = []

    def search(self, query):
        self.queries.append(query)
        if len(self.queries) == 1:
            identifiers = ('PMC1', 'PMC2')
        elif '"test conditions"' in query or ' OR ' in query and ' AND ' not in query:
            identifiers = ('PMC3',)
        else:
            identifiers = ('PMC4',)
        return [{
            'url': f'https://example.org/metadata/{identifier}',
            'title': 'Humidity coating stability metadata',
            'text': 'Humidity coating stability metadata',
            'license_status': 'synthetic fixture',
            'origin': 'fixture_metadata',
            'pmcid': identifier,
            'is_open_access': True,
        } for identifier in identifiers]

    def fulltext(self, identifier):
        self.fetches.append(identifier)
        studies = {
            'PMC1': ('PMC1', 'increased', 25),
            'PMC2': self.first_pair,
            'PMC3': ('PMC3', 'decreased', 25),
            'PMC4': ('PMC4', 'increased', 40),
        }
        study, direction, temperature = studies[identifier]
        return {
            'url': f'https://example.org/fulltext/{identifier}',
            'title': 'Humidity coating stability',
            'text': f'Humidity {direction} coating stability during exposure at {temperature} °C and 60% RH for 24 h.',
            'license_status': 'synthetic fixture',
            'study_id': study,
            'origin': 'fixture_fulltext',
            'document': {'references': []},
        }


@pytest.mark.parametrize(('first_pair', 'decision', 'reason'), [
    (('PMC2', 'decreased', 40), 'compare_study_conditions', 'context_mismatch'),
    (('PMC1', 'decreased', 25), 'broaden_search', 'shared_study'),
])
def test_context_aware_policy_retrieves_comparable_fixture_under_same_budget(
    tmp_path, monkeypatch, first_pair, decision, reason,
):
    import ares.research as research
    from ares.retrieval import DENSE

    def lexical_only(*args):
        raise OSError('No model in deterministic policy comparison')

    monkeypatch.setattr(DENSE, 'load', lexical_only)
    monkeypatch.setattr(DENSE, 'rerank', lexical_only)

    def evaluate(folder):
        provider = SnapshotProvider(first_pair)
        api = client(tmp_path / folder, provider=provider)
        pid = project(api)
        rid = run(api, pid, external=True)
        route = f'/projects/{pid}/runs/{rid}'
        report = api.get(route + '/report').raise_for_status().json()
        assert report['assessment'] == 'inconclusive'
        assert len(provider.queries) == 2 and len(provider.fetches) == 3
        assert all('60% RH' not in query and '°C' not in query for query in provider.queries)
        return report, provider

    report, provider = evaluate('context')
    audit = report['collection']['adaptation']
    assert audit['decision'] == decision
    assert audit['before']['disagreement_routes'][reason] == 1
    assert audit['before']['disagreement_routes']['unresolved'] == 0
    assert provider.fetches[-1] == 'PMC3'
    assert any(citation['study_id'] == 'PMC3' and '25 °C' in citation['quote']
               for citation in report['citations'])

    # The previous policy sent any opposing wording to this query, even when a
    # known study identifier or measured condition already qualified the signal.
    def previous_policy(question, signals):
        assert signals['potential_disagreements'] == 1
        return ('counterevidence', '"humidity" AND "coating" AND "stability" AND (replication OR "no effect" OR disagreement OR comparison)',
                'The first retrieval flagged potentially opposing findings.')

    monkeypatch.setattr(research, 'follow_up', previous_policy)
    baseline, baseline_provider = evaluate('baseline')
    assert baseline_provider.fetches[-1] == 'PMC4'
    assert not any(citation['study_id'] == 'PMC3' for citation in baseline['citations'])


def test_conflicting_human_reviews_do_not_trigger_a_counterevidence_search():
    from ares.collection import evidence_signals, follow_up

    citations = [
        {'label': 'S1', 'study_id': 'PMC1'},
        {'label': 'S2', 'study_id': 'PMC2'},
    ]
    findings = [{'citation': citation['label']} for citation in citations]
    signals = evidence_signals(findings, citations, {
        'potential_disagreements': [{'reviewed_context': {'state': 'review-conflict'}}],
    })
    assert signals['disagreement_routes']['review_conflict'] == 1
    assert signals['disagreement_routes']['unresolved'] == 0
    assert follow_up('How does humidity affect coating stability?', signals) is None
