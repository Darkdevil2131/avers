import React from 'react';
const phases=[
  {name:'Research planner',kind:'Bounded policy',stages:['plan','planner_decision'],detail:p=>p.reason||p.plan?.task_type||'Research objective recorded'},
  {name:'Literature collector',kind:'Open-access APIs',stages:['external_search_started','external_search_completed','spider_fetch','document_ingested','document_rejected','external_search_failed','collection_summary'],detail:p=>p.message||p.status||p.pmcid||(p.count!==undefined?`${p.count} metadata records`:'Collection requested')},
  {name:'Evidence retrieval',kind:'Project RAG',stages:['memory_retrieval','retrieve','audit'],detail:p=>p.exact_spans_checked!==undefined?`${p.exact_spans_checked} citation spans checked`:p.passages!==undefined?`${p.passages} passages retrieved`:p.reason||p.mode||'Retrieval recorded'},
  {name:'Hypothesis proposer',kind:'Optional local model',stages:['reasoner_started','reasoner_completed','hypothesize'],detail:p=>p.reason||p.status||(p.proposals!==undefined?`${p.proposals} ${p.type}`:'Inference requested')},
  {name:'Evidence critic',kind:'Rules · human review required',stages:['critic'],detail:p=>p.reason||'Review decision recorded'},
  {name:'Report & memory',kind:'Persistent evidence record',stages:['report'],detail:()=> 'Report saved · scientific assessment inconclusive'},
];
export default function Workflow({events=[],run}){
  return <section className="workflow" aria-label="Research workflow">
    <div className="workflow-heading"><div><p className="eyebrow">RESEARCH OPERATIONS</p><h2>One objective. An inspectable workflow.</h2></div><span className="run-status">{run?.status||'No run selected'}</span></div>
    <p className="workflow-note">These are the implemented research roles. Status comes from recorded events; it does not measure intelligence or scientific correctness.</p>
    <div className="workflow-grid">{phases.map((phase,index)=>{
      const relevant=events.filter(e=>phase.stages.includes(e.stage));
      const rejectedModel=relevant.findLast(e=>e.stage==='reasoner_completed'&&['rejected','unavailable'].includes(e.payload?.status));
      const event=rejectedModel||relevant.at(-1);
      const interrupted=['failed','cancelled'].includes(run?.status);
      const active=event&&['external_search_started','spider_fetch','reasoner_started'].includes(event.stage)&&['running','queued'].includes(run?.status);
      const problem=event&&(event.stage.includes('failed')||event.stage==='document_rejected'||['rejected','unavailable','partial'].includes(event.payload?.status));
      const status=problem?'Needs attention':active?'In progress':event?'Recorded':interrupted?'Not reached':'Not observed';
      return <article className={'workflow-step '+(problem?'attention':active?'working':event?'recorded':'pending')} key={phase.name}>
        <div className="step-top"><span className="step-number">0{index+1}</span><span>{status}</span></div>
        <h3>{phase.name}</h3><small>{phase.kind}</small>
        <p>{event?phase.detail(event.payload||{}):'No event recorded for this role.'}</p>
        {event&&<details><summary>Inspect {relevant.length} recorded events</summary>{relevant.map((item,i)=><div key={item.id||i}><strong>{item.stage}</strong><pre>{JSON.stringify(item.payload,null,2)}</pre></div>)}</details>}
      </article>;
    })}</div>
  </section>;
}
