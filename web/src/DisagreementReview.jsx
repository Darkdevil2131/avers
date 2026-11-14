import React from 'react';

const labels = {
  'context-mismatched': 'Reviewed fields differ',
  'compatible': 'Reviewed fields match',
  'unverified': 'Context remains unverified',
  'review-conflict': 'Context reviews disagree',
};

const conditionLabels = {
  temperature: 'Temperature',
  relative_humidity: 'Relative humidity',
  duration: 'Duration',
};

export function ReportedExposure({values}) {
  const fields = Object.entries(values || {});
  if (!fields.length) return null;
  return <details>
    <summary>Conditions stated in this finding</summary>
    <ul>{fields.map(([field, value]) => <li key={field}>
      {conditionLabels[field]}{value.stage ? ' · ' + value.stage : ''}: {value.quote} (characters {value.start_offset}–{value.end_offset})
    </li>)}</ul>
  </details>;
}

export default function DisagreementReview({pair}) {
  const context = pair.reviewed_context;
  return <section className="citation">
    <h4>{pair.left} / {pair.right} · {labels[context?.state] || 'Potential disagreement'}</h4>
    <p>{pair.reason}</p>
    {pair.left_statement && <blockquote>{pair.left_statement}</blockquote>}
    {pair.right_statement && <blockquote>{pair.right_statement}</blockquote>}
    {pair.same_study_identifier && <p className="warning">Both citations share a study identifier.</p>}
    {pair.reported_exposure_comparison?.length > 0 && <div>
      <p>Exposure values stated in both findings</p>
      <ul>{pair.reported_exposure_comparison.map(item => <li key={item.field}>
        {conditionLabels[item.field]}: {item.left.quote} vs. {item.right.quote} ({item.state})
      </li>)}</ul>
      <p>Study comparability still requires review.</p>
    </div>}
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
