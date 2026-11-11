import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Scene from './Scene';
import Evidence from './Evidence';
import Memory from './Memory';
import './style.css';

const STAGES = {
  reasoner_started: 'Preparing local reasoning', reasoner_completed: 'Local reasoning finished', planner_decision: 'Research strategy adjusted', queued: 'Research queued', plan: 'Research plan created',
  external_search_started: 'Searching Europe PMC',
  spider_fetch: 'Fetching open-access document', document_ingested: 'Full text stored', document_rejected: 'Document unavailable or license rejected', memory_retrieval: 'Retrieving project evidence', extract: 'Extracting candidate findings', critic: 'Checking evidence limits', hypothesize: 'Proposing follow-up tests', external_search_completed: 'Metadata received', external_search_failed: 'Source unavailable',
  retrieve: 'Project passages retrieved', audit: 'Citation spans checked',
  report: 'Report saved', failed: 'Research failed', cancelled: 'Research cancelled',
};
const TERMINAL = new Set(['completed', 'failed', 'cancelled']);
const safeLink = value => /^https?:\/\//i.test(value) ? value : undefined;

export function App() {
  const [token, setToken] = useState(''), [entry, setEntry] = useState('');
  const [user, setUser] = useState(null), [error, setError] = useState('');
  const [projects, setProjects] = useState([]), [project, setProject] = useState(null);
  const [sources, setSources] = useState([]), [runs, setRuns] = useState([]);
  const [run, setRun] = useState(null), [events, setEvents] = useState([]), [report, setReport] = useState(null);
  const [question, setQuestion] = useState(''), [external, setExternal] = useState(false);
  const [tab, setTab] = useState('research'), [modal, setModal] = useState(null), [busy, setBusy] = useState(false);
  const [reduced, setReduced] = useState(window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const activeProject = useRef(null);
  const cited = useMemo(() => new Set(report?.citations.map(c => c.source_id) || []), [report]);

  async function api(path, options = {}, auth = token) {
    const response = await fetch(path, { ...options, headers: {
      Authorization: 'Bearer ' + auth, ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers,
    } });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the form values and try again.');
    return data;
  }

  async function login(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const session = await api('/session', {}, entry);
      const list = await api('/projects', {}, entry);
      setToken(entry); setEntry(''); setUser(session); setProjects(list); setProject(list[0] || null);
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  }

  async function refresh(projectId) {
    const [sourceList, runList] = await Promise.all([api('/projects/' + projectId + '/sources'), api('/projects/' + projectId + '/runs')]);
    if (activeProject.current === projectId) { setSources(sourceList); setRuns(runList); }
  }

  useEffect(() => {
    activeProject.current = project?.id || null;
    setSources([]); setRuns([]); setRun(null); setReport(null); setEvents([]); setError('');
    if (project) refresh(project.id).catch(exc => setError(exc.message));
  }, [project?.id]);

  useEffect(() => {
    if (!run || !project) return;
    const controller = new AbortController();
    const projectId = project.id, runId = run.id;
    let latest = 0;
    async function load() {
      const prefix = '/projects/' + projectId + '/runs/' + runId;
      const response = await fetch(prefix + '/stream', { signal: controller.signal, headers: { Authorization: 'Bearer ' + token } });
      if (!response.ok) throw new Error('Could not connect to research events.');
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary;
        while ((boundary = buffer.indexOf('\n\n')) !== -1) {
          const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const data = block.split('\n').find(line => line.startsWith('data: '));
          if (!data) continue;
          const item = JSON.parse(data.slice(6));
          if (item.id && item.id > latest) {
            latest = item.id;
            setEvents(items => [...items, item]);
          }
        }
      }
      if (controller.signal.aborted || activeProject.current !== projectId) return;
      const status = await api(prefix);
      setRun(status);
      if (status.status === 'completed') setReport(await api(prefix + '/report'));
      await refresh(projectId);
      if (!TERMINAL.has(status.status)) throw new Error('Event connection ended. Reopen this run to reconnect.');
    }
    load().catch(exc => { if (exc.name !== 'AbortError') setError(exc.message); });
    return () => controller.abort();
  }, [run?.id, project?.id]);

  async function submit(event) {
    event.preventDefault(); if (!project) return;
    setBusy(true); setError('');
    try {
      const created = await api('/projects/' + project.id + '/runs', {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ question, external }),
      });
      setEvents([]); setReport(null); setRun({ ...created, question }); setTab('research');
      await refresh(project.id);
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  }

  async function createProject(event) {
    event.preventDefault(); setBusy(true);
    const name = new FormData(event.currentTarget).get('name');
    try {
      const created = await api('/projects', { method: 'POST', body: JSON.stringify({ name }) });
      setProjects([created, ...projects]); setProject(created); setModal(null);
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  }

  async function addSource(event) {
    event.preventDefault(); setBusy(true);
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api('/projects/' + project.id + '/sources', { method: 'POST', body: JSON.stringify(data) });
      setModal(null); await refresh(project.id);
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  }

  async function review(event) {
    event.preventDefault(); setBusy(true);
    const data = Object.fromEntries(new FormData(event.currentTarget));
    try {
      await api('/projects/' + project.id + '/sources/' + modal.source.id + '/review', { method: 'POST', body: JSON.stringify(data) });
      setModal(null); await refresh(project.id);
      if (report) setReport(await api('/projects/' + project.id + '/runs/' + run.id + '/report'));
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  }

  async function tool(event) {
    event.preventDefault(); setBusy(true);
    const values = new FormData(event.currentTarget).get('values').split(/[\s,]+/).filter(Boolean).map(Number);
    try {
      const result = await api('/projects/' + project.id + '/tools/describe_sample', { method: 'POST', body: JSON.stringify({ parameters: { values } }) });
      setModal({ type: 'tool', result: result.result });
    } catch (exc) { setError(exc.message); } finally { setBusy(false); }
  }

  function download() {
    const blob = new Blob([report.markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob), link = document.createElement('a');
    link.href = url; link.download = 'ares-report.md'; link.click(); URL.revokeObjectURL(url);
  }

  useEffect(() => {
    if (user && !modal) return;
    const previous = document.activeElement;
    const dialog = document.querySelector('.overlay .modal');
    const focusable = () => [...(dialog?.querySelectorAll('button:not(:disabled),input,select,textarea,a[href]') || [])];
    focusable()[0]?.focus();
    function keys(event) {
      if (event.key === 'Escape' && user) setModal(null);
      if (event.key === 'Tab') {
        const list = focusable(), index = list.indexOf(document.activeElement);
        if (event.shiftKey && index <= 0) { event.preventDefault(); list.at(-1)?.focus(); }
        else if (!event.shiftKey && index === list.length - 1) { event.preventDefault(); list[0]?.focus(); }
      }
    }
    document.addEventListener('keydown', keys);
    return () => { document.removeEventListener('keydown', keys); previous?.focus(); };
  }, [modal?.type, !!user]);

  const selectedEvent = events.at(-1);
  const running = run && !TERMINAL.has(run.status);
  return <div className="app">
    <aside inert={!user || !!modal}>
      <div className="brand"><div className="brand-mark">A</div><div>ARES<small>Scientific intelligence</small></div></div>
      <div className="sidebar-label">WORKSPACE</div>
      <button className="project-select" onClick={() => setModal({ type: 'projects' })} disabled={!user}>
        <span className="folder">▱</span><span>{project?.name || 'Choose a project'}</span><span>⌄</span>
      </button>
      <nav aria-label="Workspace navigation">
        <button disabled={!project} className={tab === 'memory' ? 'active' : ''} onClick={() => setTab('memory')}>▣ Research memory</button>
        <button disabled={!project} className={tab === 'evidence' ? 'active' : ''} onClick={() => setTab('evidence')}>◇ Evidence review</button>
        <button className={tab === 'research' ? 'active' : ''} onClick={() => setTab('research')}><span>◎</span> Research</button>
        <button className={tab === 'sources' ? 'active' : ''} onClick={() => setTab('sources')}><span>▤</span> Source library <b>{sources.length}</b></button>
        <button disabled={!project} onClick={() => setModal({ type: 'tool' })}><span>∑</span> Calculations</button>
      </nav>
      <div className="sidebar-label history-label">RESEARCH HISTORY</div>
      <div className="history">{runs.length ? runs.map(item => <button key={item.id} className={run?.id === item.id ? 'selected' : ''} onClick={() => { if (run?.id !== item.id) { setEvents([]); setReport(null); setRun(item); } setTab('research'); }}>
        <i className={'dot ' + item.status}/><span>{item.question}</span>
      </button>) : <p>Saved research will appear here.</p>}</div>
      <div className="sidebar-bottom"><span className="avatar">{user?.username.slice(0, 1).toUpperCase() || 'A'}</span><div>{user?.username || 'Private workspace'}<small>₹0 external service spend</small></div>{user && <button aria-label="Sign out" onClick={() => location.reload()}>↪</button>}</div>
    </aside>
    <main inert={!user || !!modal}>
      <header><span>Workspace <span className="slash">/</span> {project?.name || 'Research'}</span><div className="header-right"><span className="status-light"/> {user?.mode || 'Research workspace'} <button className="quiet" onClick={() => setReduced(!reduced)} aria-pressed={reduced}>2D view</button></div></header>
      {error && <div className="error" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss error">×</button></div>}
      <div className="main-content">
        <div className="page-title"><div><p className="eyebrow">EVIDENCE FIRST</p><h1>{tab === 'research' ? 'Follow the evidence.' : tab === 'memory' ? 'Keep research reviewable.' : tab === 'evidence' ? 'Review the scientific context.' : 'Your research sources.'}</h1><p>{tab === 'research' ? 'Ask a question. Inspect the sources. Keep the evidence traceable.' : 'Versioned source text, provenance, and review status in one place.'}</p></div><button className="secondary" disabled={!project || project.role === 'viewer'} onClick={() => setModal({ type: 'source' })}>＋ Add source</button></div>

        {tab === 'research' ? <>
          <section className="map-card">
            <div className="map-top"><span><i className="status-light"/>{running ? STAGES[selectedEvent?.stage] || 'Waiting for worker' : 'Research activity'}</span><span>{sources.length} stored sources · {report?.citations.length || 0} cited passages</span></div>
            <Scene sources={sources} cited={cited} reduced={reduced} activity={selectedEvent} running={running}/>
            <div className="map-bottom"><span>PROJECT KNOWLEDGE</span><span className="legend"><i/> Stored source <i className="lime"/> Cited in this report</span></div>
          </section>
          <form className="question-box" onSubmit={submit}>
            <label htmlFor="question">What would you like to investigate?</label>
            <textarea id="question" value={question} onChange={event => setQuestion(event.target.value)} minLength={8} maxLength={2000} required placeholder="How does humidity affect the stability of protective coatings?" rows={2}/>
            <div className="question-actions"><label className="checkbox"><input type="checkbox" checked={external} onChange={event => setExternal(event.target.checked)}/> Collect open-access literature</label><button className="primary" disabled={!project || busy || project.role === 'viewer'}>Start research <span>↗</span></button></div>
          </form>
          <div className="results-grid">
            <section className="report-panel">
              <div className="section-heading"><h2>Evidence report</h2>{report && <button className="quiet" onClick={download}>↓ Export</button>}</div>
              {report ? <>
                <div className="assessment"><span className="assessment-badge">Inconclusive</span><span>Scientific assessment requires review</span></div>
                {report.outdated_sources.length > 0 && <p className="warning">Source reviews have changed since this report was saved. Start a new run to refresh the evidence.</p>}
                <h3>{report.question}</h3>{report.summary_status && <small>{report.summary_status}</small>}<p>{report.summary}</p>{report.reasoner && <p>Local reasoning: {report.reasoner.status}{report.reasoner.reason ? ' — ' + report.reasoner.reason : ''}</p>}
                {report.retrieval && <p className="warning">Retrieval: {report.retrieval.mode} · {report.retrieval.dense_available ? 'Dense embeddings + keyword search' : report.retrieval.reason || 'No indexed passages'}</p>}
                {report.findings?.length > 0 && <section><h3>Extracted candidate findings</h3><p>Exact source statements. Scientific meaning and study context still require review.</p>{report.findings.map((f,i)=><article className="citation" key={i}><span>{f.citation} · {f.method}</span><blockquote>{f.statement}</blockquote><p>Measurements found: {f.measurements.join(', ')||'none'}</p></article>)}</section>}
                {report.critique && <details><summary>Evidence critic decision</summary><p>{report.critique.reason}</p>{report.critique.missing_checks.map(x=><p key={x}>{x}</p>)}{report.critique.potential_disagreements.map((x,i)=><p key={i}>{x.left} / {x.right}: {x.reason}</p>)}{report.critique.rejected_proposals?.map((r,i)=><p key={'rejected'+i}>Rejected model proposal: {r.check.reasons.join('; ')}</p>)}</details>}
                {report.hypotheses?.map((h,i)=><article className="citation" key={'h'+i}><h3>Follow-up proposal · requires review</h3><p>{h.statement}</p><blockquote>{h.basis_quote}</blockquote><p>{h.mechanism}</p><p>Falsification: {h.falsification}</p><p>No experiment has been executed. Novelty has not been established.</p></article>)}
                {report.citations.map(citation => <article className="citation" key={citation.label}>
                  <div className="citation-heading"><span className="citation-label">{citation.label}</span><span>{citation.origin.endsWith('_metadata') ? 'Bibliographic metadata' : citation.origin.endsWith('_fulltext') ? 'Licensed full-text passage' : 'Source passage'}</span></div>
                  <h4>{citation.title}</h4><blockquote>{citation.quote}</blockquote>
                  <div className="citation-meta"><a href={safeLink(citation.url)} target="_blank" rel="noreferrer">{citation.url}</a><span>Characters {citation.start_offset}–{citation.end_offset}</span></div>
                  {project.role === 'owner' && <div><button className="quiet" onClick={async()=>{try{await api('/projects/'+project.id+'/runs/'+run.id+'/feedback',{method:'POST',body:JSON.stringify({source_id:citation.source_id,relevant:true})});setError('Relevance feedback saved for future similar queries.')}catch(e){setError(e.message)}}}>Useful source</button><button className="quiet" onClick={async()=>{try{await api('/projects/'+project.id+'/runs/'+run.id+'/feedback',{method:'POST',body:JSON.stringify({source_id:citation.source_id,relevant:false})});setError('Relevance feedback saved for future similar queries.')}catch(e){setError(e.message)}}}>Not relevant</button></div>}
                  <details><summary>Provenance</summary><p>{citation.license_status}</p><code>SHA-256 {citation.digest}</code><p>Stored {new Date(citation.retrieved_at).toLocaleString()}</p></details>
                </article>)}
                <div className="limitations"><h4>Assessment limits</h4>{report.limitations.map(item => <p key={item}>{item}</p>)}</div>
              </> : <div className="empty-report"><span>⌕</span><h3>{running ? 'Following the research workflow' : 'A clear path back to every source'}</h3><p>{running ? 'Progress appears as the backend finishes each step.' : 'Add source text and start a question to build an evidence report with exact citations.'}</p></div>}
            </section>
            <section className="activity-panel"><div className="section-heading"><h2>Activity</h2>{running && <button className="quiet" onClick={async () => { try { await api('/projects/' + project.id + '/runs/' + run.id + '/cancel', { method: 'POST' }); } catch (exc) { setError(exc.message); } }}>Cancel</button>}</div>
              {events.length ? <ol className="timeline">{events.map(event => <li key={event.id}><span className={'event-icon ' + (event.stage.includes('failed') ? 'failed' : '')}/><div><strong>{STAGES[event.stage] || event.stage}</strong><p>{event.payload.message || (event.payload.count !== undefined ? event.payload.count + ' records received' : event.payload.exact_spans_checked !== undefined ? event.payload.exact_spans_checked + ' exact spans checked' : event.payload.passages !== undefined ? event.payload.passages + ' matching passages' : event.stage === 'report' ? 'Report persisted with citations' : '')}</p><time>{new Date(event.created_at).toLocaleTimeString()}</time></div></li>)}</ol> : <p className="muted">Run activity will appear here.</p>}
            </section>
          </div>
        </> : tab === 'memory' && project ? <Memory key={project.id} api={api} project={project}/> : tab === 'evidence' && project ? <Evidence key={project.id} api={api} project={project} sources={sources}/> : <section className="source-list">
          {!sources.length && <div className="empty-report"><h3>No sources yet</h3><p>Add text you have permission to use, with its source URL and license information.</p></div>}
          {sources.map(source => <article key={source.id}><div><span className="source-icon">▤</span></div><div className="source-content"><h3>{source.title}</h3><a href={safeLink(source.url)} target="_blank" rel="noreferrer">{source.url}</a><p>{source.text.slice(0, 220)}{source.text.length > 220 ? '…' : ''}</p><span className={'source-status ' + source.status}>{source.status}</span><span className="source-kind">{source.origin.replaceAll('_', ' ')}</span></div><button className="quiet" disabled={project?.role === 'viewer'} onClick={() => setModal({ type: 'review', source })}>Review</button></article>)}
        </section>}
        <footer>ARES <span>Evidence stays traceable. Conclusions stay open to review.</span></footer>
      </div>
    </main>
    {!user && <div className="overlay"><form className="modal login" onSubmit={login}><div className="brand-mark">A</div><p className="eyebrow">PRIVATE RESEARCH WORKSPACE</p><h2>Welcome to ARES.</h2><p>Use the access token configured in your hosted environment.</p><label htmlFor="token">Access token</label><input id="token" type="password" autoComplete="off" value={entry} onChange={event => setEntry(event.target.value)} required minLength={32}/><button className="primary" disabled={busy}>Open workspace ↗</button>{error && <p className="error" role="alert">{error}</p>}</form></div>}
    {user && modal && <div className="overlay" onClick={event => { if (event.target === event.currentTarget) setModal(null); }}><div className="modal" role="dialog" aria-modal="true" aria-label={modal.type}><button className="close" aria-label="Close dialog" onClick={() => setModal(null)}>×</button>
      {error && <p role="alert" className="error">{error}</p>}
      {modal.type === 'projects' && <><h2>Projects</h2><div className="project-options">{projects.map(item => <button key={item.id} onClick={() => { setProject(item); setModal(null); }}>{item.name}<small>{item.role}</small></button>)}</div><form onSubmit={createProject}><label htmlFor="project-name">New project</label><input id="project-name" name="name" placeholder="Materials research" required maxLength={200}/><button className="primary" disabled={busy}>Create project</button></form></>}
      {modal.type === 'source' && <form onSubmit={addSource}><h2>Add a source</h2><p>Paste text you have permission to store. The original text is preserved for exact citations.</p><label>Title<input name="title" maxLength={500} placeholder="Study title"/></label><label>Source URL or reference<input name="url" required maxLength={2000} placeholder="https://…"/></label><label>License or permission<input name="license_status" required maxLength={200} placeholder="CC BY 4.0, or your permission to use this text"/></label><label>Study identifier<input name="study_id" maxLength={500} placeholder="DOI or trial ID, if known"/></label><label>Source text<textarea name="text" required maxLength={100000} rows={7}/></label><button className="primary" disabled={busy}>Save source</button></form>}
      {modal.type === 'review' && <form onSubmit={review}><h2>Review source</h2><p>{modal.source.title}</p><label>Status<select name="status" defaultValue={modal.source.status}><option>active</option><option>retracted</option><option>excluded</option></select></label><label>Reason and supporting reference<textarea name="reason" required minLength={8} maxLength={2000} rows={4}/></label><button className="primary" disabled={busy}>Record review</button></form>}
      {modal.type === 'tool' && <form onSubmit={tool}><h2>Describe a sample</h2><p>Calculate the mean, sample standard deviation, and range of explicit observations.</p><label>Values, separated by commas<textarea name="values" required rows={4} placeholder="12, 15, 18, 21"/></label><button className="primary" disabled={busy}>Calculate</button>{modal.result && <dl className="tool-result">{Object.entries(modal.result).map(([key, value]) => <React.Fragment key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{value.toLocaleString(undefined, { maximumFractionDigits: 6 })}</dd></React.Fragment>)}</dl>}</form>}
    </div></div>}
  </div>;
}

const root = document.getElementById('root');
if (root) createRoot(root).render(<App/>);
