"""Read-time disclosures without changing the immutable saved report."""


def export_markdown(saved, payload, changed):
    lines=[]
    if changed:
        lines += ['> WARNING: Source reviews changed after this report was saved.',
                  '> This historical report may rely on retracted or excluded evidence. Run research again before relying on it.',
                  '> Affected source IDs: '+', '.join(sorted(set(changed))), '']
    lines += [saved, '', '## Model and proposal review disclosures', '',
              'Exact quotations establish provenance, not scientific truth. No experiment or scientific validation is implied.', '']
    reasoner=payload.get('reasoner') or {}
    lines += ['Local reasoning status: '+reasoner.get('status','not recorded')]
    if reasoner.get('reason'):lines += ['Reason: '+reasoner['reason']]
    lines += ['- '+x for x in reasoner.get('critic_warnings',[])]
    for pair in (payload.get('critique') or {}).get('potential_disagreements',[]):
        lines += ['', '### Potential evidence disagreement — requires review',
                  f"[{pair['left']}] / [{pair['right']}]: {pair['reason']}"]
        if pair.get('left_statement'):lines += [pair['left_statement']]
        if pair.get('right_statement'):lines += [pair['right_statement']]
        if pair.get('same_study_identifier'):lines += ['Both citations share a study identifier; do not count them as independent studies.']
        for comparison in pair.get('reported_exposure_comparison', []):
            field = comparison['field'].replace('_', ' ')
            first, second = comparison['left'], comparison['right']
            lines += [f"- Reported {field} {comparison['state']}: "
                      f"{first['quote']} (characters {first['start_offset']}–{first['end_offset']}) "
                      f"vs. {second['quote']} (characters {second['start_offset']}–{second['end_offset']})."]
        context = pair.get('reviewed_context')
        if context:
            lines += [f"Reviewed context: {context['state']}. {context['reason']}"]
            if context['fields']:
                lines += ['Context fields: ' + ', '.join(context['fields'])]
            if context['review_ids']:
                lines += ['Evidence review IDs: ' + ', '.join(context['review_ids'])]
        lines += ['- '+question for question in pair.get('review_questions',[])]
    for item in (payload.get('critique') or {}).get('rejected_proposals',[]):
        lines += ['', '### Rejected model proposal', item['candidate'].get('statement','Statement not recorded')]
        lines += ['- '+x for x in item['check'].get('reasons',[])]
    for proposal in payload.get('hypotheses',[]):
        lines += ['', '### Follow-up proposal — requires review', proposal['statement'],
                  'Evidence citation: '+proposal.get('citation','not recorded'),
                  'Basis quote: '+proposal.get('basis_quote','not recorded'),
                  'Mechanism: '+proposal.get('mechanism','not established'),
                  'Falsification: '+proposal.get('falsification','not established')]
        check=proposal.get('consistency_check') or {}
        direction=check.get('direction_check') or {}
        lines += ['Direction check: '+direction.get('status','not recorded'),
                  'Passing deterministic rules is not scientific approval. Context remains unverified.']
        lines += ['- '+x for x in check.get('limitations',[])]
    return '\n'.join(lines)+'\n'
