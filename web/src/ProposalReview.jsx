import React from 'react';

const statuses = {
  potential_opposition: 'Possible opposing directions detected',
  requires_review: 'Direction comparison needs human review',
  no_opposition_detected: 'No opposing direction detected by the rules',
};
const bases = {
  negation_requires_context_review: 'Negated wording needs context',
  mixed_directions_require_context_review: 'Multiple directions need context',
  explicit_direction_word: 'Explicit direction word',
  predicative_comparison: 'Comparative statement',
  direction_not_established: 'Direction could not be established',
};

export function ExperimentPlan({plan, evidence}) {
  if (!plan) return null;
  const contrast = plan.contrast;
  return <details open={Boolean(contrast)}>
    <summary>Proposed comparison and review inputs</summary>
    <p>{plan.design}</p>
    {contrast && <p>{contrast.field.replaceAll('_', ' ')}: {contrast.left.quote} vs. {contrast.right.quote}</p>}
    {plan.matching_reported_conditions?.map(item => <p key={item.field}>
      Reported {item.field.replaceAll('_', ' ')} matches: {item.left.quote} and {item.right.quote}
    </p>)}
    {plan.controls && <p>{plan.controls}</p>}
    {evidence?.map(item => <blockquote key={item.citation + ':' + item.start_offset}>
      {item.statement}
      <cite> · [{item.citation}] Characters {item.start_offset}–{item.end_offset}</cite>
    </blockquote>)}
    <ul>{plan.required_inputs.map(input => <li key={input}>{input}</li>)}</ul>
    {plan.reason && <p>Sample size pending. {plan.reason}</p>}
  </details>;
}

export default function ProposalReview({check}) {
  const direction = check?.direction_check;
  return <aside aria-label="Proposal review limits">
    <p><strong>{statuses[direction?.status] || 'Direction check unavailable for this report'}</strong></p>
    {direction && <p>Proposal wording: {bases[direction.hypothesis_basis] || 'Unrecognized check result'}. Evidence wording: {bases[direction.evidence_basis] || 'Unrecognized check result'}.</p>}
    {check?.reasons?.map((reason,i)=><p key={i}>{reason}</p>)}
    <p>Scientific support has not been validated. Passing these rules is not approval of the hypothesis.</p>
    {check?.limitations?.map((limit,i)=><p key={i}>{limit}</p>)}
  </aside>;
}
