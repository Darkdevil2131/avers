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
    return export_markdown(bundle['saved_markdown'], report, [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        with args.bundle.open('rb') as stream:
            encoded = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(encoded) > MAX_BUNDLE_BYTES:
            raise ValueError('Replay bundle exceeds size limit.')
        rendered = replay_markdown(json.loads(encoded))
        with args.output.open('x', encoding='utf-8') as output:
            output.write(rendered)
    except (OSError, TypeError, ValueError, KeyError, AttributeError) as exc:
        parser.exit(1, f'Replay failed: {exc}\n')


if __name__ == '__main__':
    main()
