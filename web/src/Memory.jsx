import React,{useEffect,useState} from 'react';
export default function Memory({api,project}){
 const [items,setItems]=useState([]),[error,setError]=useState('');
 const prefix='/projects/'+project.id+'/memory';
 async function refresh(){setItems(await api(prefix))}
 useEffect(()=>{refresh().catch(e=>setError(e.message))},[project.id]);
 async function review(event,id){event.preventDefault();const data=Object.fromEntries(new FormData(event.currentTarget));try{await api(prefix+'/'+id+'/review',{method:'POST',body:JSON.stringify(data)});await refresh()}catch(e){setError(e.message)}}
 return <section className="evidence-workspace"><h2>Research memory</h2><p>Every completed run is recorded. Approval is a human review decision; it does not retrain the model or turn a hypothesis into a fact.</p>{error&&<p role="alert">{error}</p>}{!items.length&&<p>No completed research memories yet.</p>}{items.map(item=><article className="citation" key={item.id}><h3>{item.content.question}</h3><p>{item.status} {item.stale?'· source reviews have changed':''}</p><p>{item.content.findings.length} extracted candidates · {item.content.source_ids.length} cited passages</p>{project.role==='owner'&&<form className="review-form" onSubmit={e=>review(e,item.id)}><label>Review decision<select name="status"><option value="excluded">Reject</option><option value="active" disabled={item.stale}>Approve reviewed memory</option></select></label><label>Review reason<textarea name="reason" required minLength={8} maxLength={2000}/></label><button className="secondary">Save memory review</button></form>}</article>)}</section>
}
