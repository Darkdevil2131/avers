import React, {useEffect, useState} from 'react';

export default function RuntimeStatus({token}) {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    let controller, timer;
    let disposed = false;
    setStatus(null);
    async function refresh() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch('/runtime', {
          signal: controller.signal, headers: {Authorization: 'Bearer ' + token},
        });
        if (!response.ok) throw new Error('Runtime status unavailable');
        const data = await response.json();
        if (!data || !['connected', 'unavailable'].includes(data.database)) throw new Error('Invalid runtime status');
        if (!disposed) setStatus(data);
      } catch {
        if (!disposed) setStatus({database: 'unknown', worker: 'unknown'});
      } finally {
        clearTimeout(timeout);
        if (!disposed) timer = setTimeout(refresh, 10000);
      }
    }
    refresh();
    return () => {disposed = true; controller?.abort(); clearTimeout(timer);};
  }, [token]);
  let message = 'Checking API, database and research worker…';
  if (status) {
    if (status.database !== 'connected') message = 'Server status unavailable. Check the API connection and database configuration.';
    else if (status.worker === 'in_process') message = 'Database connected. Research runs inside the API process.';
    else if (status.worker === 'connected') message = 'Database connected. Research worker heartbeat received.';
    else message = 'Database connected, but no recent research worker heartbeat. Queued research is waiting for a worker connected to this database.';
  }
  return <section className="runtime-status" aria-label="Server connection" role="status">
    <p>{message}</p>
    {Array.isArray(status?.reasoning) && status.reasoning.length > 0 && <p>{status.reasoning.every(value => value === 'configured')
      ? 'Local model configured. Inference results appear in each report.'
      : 'Local model unavailable on one or more research processes. Extractive reports remain available.'}</p>}
  </section>;
}
