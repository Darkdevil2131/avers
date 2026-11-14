import React from 'react';

export default function ReviewedClaim({claim}) {
  return <section aria-label="Reviewed claim assessment">
    <h3>Reviewed claim</h3>
    <p><strong>{claim.statement}</strong></p>
    <p>{claim.reason}</p>
    <p>Based on recorded reviewer judgments. Study independence remains unverified.</p>
    {claim.evidence.map(item => <article className="citation" key={item.id}>
      <h4>{item.title}</h4>
      <p>{item.stance} · {item.exclusions.length
        ? 'Excluded: ' + item.exclusions.map(reason => reason.replaceAll('-', ' ')).join(', ')
        : 'Included in assessment'}</p>
      {item.quote && <blockquote>{item.quote}</blockquote>}
      {item.quote_truncated && <p>Showing the first 2,000 characters of the linked span.</p>}
      <p>{item.rationale}</p>
      {item.context.fields.length > 0 && <p>Context fields: {item.context.fields.join(', ')}</p>}
      <details>
        <summary>Evidence provenance</summary>
        <p>{item.url}</p>
        <p>Characters {item.start_offset}–{item.end_offset}</p>
        <p>Study identifier {item.study_id}</p>
        <p>Review {item.id}</p>
        <code>SHA-256 {item.digest}</code>
      </details>
    </article>)}
  </section>;
}
