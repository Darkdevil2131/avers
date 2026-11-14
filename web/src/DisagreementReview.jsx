import React from 'react';

const labels = {
  'context-mismatched': 'Reviewed fields differ',
  'compatible': 'Reviewed fields match',
  'unverified': 'Context remains unverified',
  'review-conflict': 'Context reviews disagree',
};

export default function DisagreementReview({pair}) {
  const context = pair.reviewed_context;
  return <section className="citation">
    <h4>{pair.left} / {pair.right} · {labels[context?.state] || 'Potential disagreement'}</h4>
    <p>{pair.reason}</p>
    {pair.left_statement && <blockquote>{pair.left_statement}</blockquote>}
    {pair.right_statement && <blockquote>{pair.right_statement}</blockquote>}
    {pair.same_study_identifier && <p className="warning">Both citations share a study identifier.</p>}
    {context && <div>
      <p>{context.reason}</p>
      {context.fields.length > 0 && <p>Fields for review: {context.fields.map(field => field.replaceAll('_', ' ')).join(', ')}</p>}
      {context.review_ids.length > 0 && <details>
        <summary>Evidence review records</summary>
        <ul>{context.review_ids.map(id => <li key={id}><code>{id}</code></li>)}</ul>
      </details>}
    </div>}
    {pair.review_questions?.map(question => <p key={question}>{question}</p>)}
  </section>;
}
