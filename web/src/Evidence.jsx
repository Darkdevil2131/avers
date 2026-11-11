import React, {useEffect, useState} from 'react';
const fields = ['subject','variable','units','population_or_material','conditions','study_design','outcome','measurement','timeframe'];
function Fingerprint(){return <fieldset><legend>Scientific context — leave unknown values blank</legend>{fields.map(name=><label key={name}>{name.replaceAll('_',' ')}<input name={'fp_'+name} maxLength={100}/></label>)}</fieldset>}
export default function Evidence({api, project, sources}) {
  const [claims,setClaims]=useState([]),[hypotheses,setHypotheses]=useState([]),[mode,setMode]=useState('claim'),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const prefix='/projects/'+project.id;
  async function refresh(){const [c,h]=await Promise.all([api(prefix+'/claims'),api(prefix+'/hypotheses')]);setClaims(c);setHypotheses(h)}
  useEffect(()=>{refresh().catch(e=>setError(e.message))},[project.id]);
  async function submit(event){
    event.preventDefault();const form=event.currentTarget;const data=Object.fromEntries(new FormData(form));setBusy(true);setError('');
    const fingerprint=Object.fromEntries(fields.map(f=>[f,data['fp_'+f]||'']));
    let path,body;
    if(mode==='claim'){path='/claims';body={statement:data.statement,fingerprint}}
    else if(mode==='evidence'){path='/claims/'+data.claim_id+'/evidence';body={source_id:data.source_id,start_offset:Number(data.start_offset),end_offset:Number(data.end_offset),stance:data.stance,rationale:data.rationale,fingerprint}}
    else {path='/hypotheses';body={statement:data.statement,mechanism:data.mechanism,falsification:data.falsification,predecessor:data.predecessor||null}}
    try{await api(prefix+path,{method:'POST',body:JSON.stringify(body)});form.reset();await refresh()}catch(e){setError(e.message)}finally{setBusy(false)}
  }
  return <section className="evidence-workspace"><div className="section-heading"><h2>Evidence review & hypotheses</h2></div><p>Record human-reviewed relationships and experimental proposals. Assessment labels summarize your entries; they are not calibrated scientific verdicts.</p>
    <div className="review-tabs">{['claim','evidence','hypothesis'].map(value=><button className={mode===value?'primary':'secondary'} key={value} onClick={()=>{setMode(value);setError('')}}>{value==='claim'?'Record claim':value==='evidence'?'Link evidence':'Propose hypothesis'}</button>)}</div>
    {error&&<p role="alert" className="error">{error}</p>}
    <form className="review-form" key={mode} onSubmit={submit}>
      {mode==='evidence'?<><label>Claim<select name="claim_id" required><option value="">Choose a claim</option>{claims.map(c=><option key={c.id} value={c.id}>{c.statement}</option>)}</select></label><label>Source<select name="source_id" required><option value="">Choose a source</option>{sources.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select></label><p>Offsets count Unicode characters from zero. The end is exclusive. The server preserves the exact quoted text.</p><label>Start offset<input name="start_offset" type="number" min="0" required/></label><label>End offset<input name="end_offset" type="number" min="1" required/></label><label>Reviewer stance<select name="stance"><option>neutral</option><option>supports</option><option>contradicts</option></select></label><label>Rationale<textarea name="rationale" minLength={8} maxLength={2000} required/></label></>:<label>Statement<textarea name="statement" minLength={8} maxLength={2000} required/></label>}
      {mode==='hypothesis'?<><label>Proposed mechanism<textarea name="mechanism" minLength={8} maxLength={3000} required/></label><label>Observation that would falsify it<textarea name="falsification" minLength={8} maxLength={3000} required/></label><label>Revision of<select name="predecessor"><option value="">New proposal</option>{hypotheses.map(h=><option key={h.id} value={h.id}>v{h.version}: {h.statement}</option>)}</select></label></>:<Fingerprint/>}
      <button className="primary" disabled={busy||project.role==='viewer'}>Save {mode}</button>
    </form>
    <h2>Claims</h2>{claims.length===0&&<p>No reviewed claims yet.</p>}{claims.map(c=><article className="citation" key={c.id}><h3>{c.statement}</h3><span className="assessment-badge">{c.assessment}</span><p>{c.basis} · {c.study_groups} study identifier groups · independence unverified</p>{c.evidence.map(e=><details key={e.id}><summary>{e.stance} · {e.context.state} · source {e.source_status}</summary><blockquote>{e.quote}</blockquote><p>{e.rationale}</p><p>Context fields needing review: {e.context.fields.join(', ')||'none'}</p></details>)}</article>)}
    <h2>Hypothesis history</h2>{hypotheses.length===0&&<p>No proposals yet.</p>}{hypotheses.map(h=><article className="citation" key={h.id}><h3>v{h.version} · {h.statement}</h3><p><strong>Mechanism:</strong> {h.mechanism}</p><p><strong>Falsification:</strong> {h.falsification}</p><small>Proposal only. No experiment has been executed.</small></article>)}
  </section>
}
