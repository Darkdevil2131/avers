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
