import React from 'react';
const valid=value=>typeof value==='string' && /^[a-f0-9]{40}$/i.test(value);
export default function BuildInfo({frontend=__ARES_BUILD_REVISION__,backend}) {
  const front=valid(frontend)?frontend.toLowerCase():'unknown';
  const back=valid(backend)?backend.toLowerCase():'unknown';
  const known=front!=='unknown' && back!=='unknown';
  return <details className="build-info"><summary>Build details</summary>
    <p>Frontend revision: <code>{front}</code></p>
    <p>Backend revision: <code>{back}</code></p>
    <p>{!known?'Build identity is incomplete; the deployed version cannot be confirmed.':front!==back?'Version mismatch: frontend and backend report different revisions.':'Frontend and backend report the same revision.'}</p>
    <p>Revision labels are supplied at build time. They do not prove this is the latest GitHub version or a verified production deployment.</p>
  </details>;
}
