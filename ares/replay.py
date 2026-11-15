"""Verify archived source snapshots and reproduce the saved Markdown offline."""

import argparse
import hashlib
import json
from pathlib import Path

from .report_export import export_markdown

FORMAT = 'ares-report-replay-v1'
MAX_SOURCE_BYTES = 12_000_000
MAX_BUNDLE_BYTES = 28_000_000


def source_references(report):
    reviewed = report.get('reviewed_claim') or {}
    return [*report['citations'], *reviewed.get('evidence', [])]


def replay_markdown(bundle):
    """Render the historical report without consulting current reviews or rerunning inference."""
    if bundle.get('format') != FORMAT:
        raise ValueError('Unsupported replay bundle format.')
    report = bundle['report']
    sources = bundle['sources']
    for snapshot in sources.values():
        actual = hashlib.sha256(snapshot['text'].encode()).hexdigest()
        if actual != snapshot['digest']:
            raise ValueError('Archived source hash does not match its text.')
    for reference in source_references(report):
        source = sources.get(reference['source_id'])
        if source is None or reference['digest'] != source['digest']:
            raise ValueError('Referenced source is missing or has a different hash.')
        if 'source-span-invalid' in reference.get('exclusions', []):
            continue
        start, end = reference['start_offset'], reference['end_offset']
        if not 0 <= start < end <= len(source['text']):
            raise ValueError('Archived reference has invalid offsets.')
        expected = source['text'][start:end]
        if reference.get('quote_truncated'):
            expected = expected[:2000]
        if reference['quote'] != expected:
            raise ValueError('Archived quote does not match the referenced source span.')
    citations = {citation['label']: citation for citation in report['citations']}
    for finding in report.get('findings', []):
        citation = citations.get(finding['citation'])
        if not citation or citation['source_id'] != finding['source_id']:
            raise ValueError('Archived finding has no matching citation.')
        start, end = finding['start_offset'], finding['end_offset']
        if not citation['start_offset'] <= start < end <= citation['end_offset']:
            raise ValueError('Archived finding falls outside its cited passage.')
        source = sources[finding['source_id']]['text']
        if source[start:end] != finding['statement']:
            raise ValueError('Archived finding does not match its source span.')
    return export_markdown(bundle['saved_markdown'], report, [])


def verify_findings(bundle):
    """Rerun extraction over archived passages using the current local models."""
    replay_markdown(bundle)
    from .agents import extract
    from .retrieval import DENSE, RERANKER_MODEL

    report = bundle['report']
    original = report.get('findings', [])
    rerun = extract(report['citations'], report['question'])
    fields = ('citation', 'source_id', 'statement', 'start_offset', 'end_offset', 'method')
    saved = [{key: item[key] for key in fields} for item in original]
    current = [{key: item[key] for key in fields} for item in rerun]
    recorded_model = (report.get('execution') or {}).get('finding_reranker') or {}
    recorded_hash = recorded_model.get('snapshot_sha256')
    current_hash = DENSE.reranker_artifact_hash if any(
        item['method'] == 'context-weighted-sentence-reranker-v2' for item in rerun
    ) else None
    identity_verified = bool(recorded_hash and current_hash and recorded_hash == current_hash
                             and recorded_model.get('model') == RERANKER_MODEL)
    identity_mismatch = bool(recorded_hash and current_hash and not identity_verified)
    return {
        'match': saved == current and not identity_mismatch,
        'saved_count': len(saved),
        'rerun_count': len(current),
        'saved': saved,
        'rerun': current,
        'scope': 'Extraction from archived cited passages with current local models. Retrieval and reasoning are not rerun.',
        'model_identity_verified': identity_verified,
        'recorded_model_sha256': recorded_hash,
        'current_model_sha256': current_hash,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--check-findings', action='store_true',
                        help='Compare current evidence extraction with the archived findings.')
    args = parser.parse_args()
    try:
        with args.bundle.open('rb') as stream:
            encoded = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(encoded) > MAX_BUNDLE_BYTES:
            raise ValueError('Replay bundle exceeds size limit.')
        bundle = json.loads(encoded)
        rendered = replay_markdown(bundle)
        if args.check_findings:
            comparison = verify_findings(bundle)
            print(json.dumps(comparison, indent=2))
            if not comparison['match']:
                raise ValueError('Evidence extraction differs from the saved findings.')
        with args.output.open('x', encoding='utf-8') as output:
            output.write(rendered)
    except (OSError, TypeError, ValueError, KeyError, AttributeError) as exc:
        parser.exit(1, f'Replay failed: {exc}\n')


if __name__ == '__main__':
    main()
