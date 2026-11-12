// @vitest-environment happy-dom
import React from 'react';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import {act, cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
vi.mock('./Scene',()=>({default:()=> <div>Source graph</div>}));
import {App} from './main';
import Evidence from './Evidence';
afterEach(()=>{cleanup();vi.restoreAllMocks()});
beforeEach(()=>{window.matchMedia=vi.fn(()=>({matches:true}));});
const project={id:'p',name:'Coatings',role:'owner'};
const reply=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
test('disconnected research reconnects without submitting a new job',async()=>{
 const user=userEvent.setup();let streams=0;
 const run={id:'r',question:'Recover interrupted research',status:'completed'};
 const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>{
  if(url==='/session')return reply({username:'researcher'});
  if(url==='/projects')return reply([project]);
  if(url.endsWith('/sources'))return reply([]);
  if(url.endsWith('/runs'))return reply([run]);
  if(url.endsWith('/stream')){
   if(++streams===1)throw new TypeError('Network connection lost');
   return new Response('event: done\ndata: {"status":"completed"}\n\n');
  }
  if(url.endsWith('/runs/r'))return reply(run);
  if(url.endsWith('/report'))return reply({summary:'Recovered saved report',outdated_sources:[],citations:[],limitations:[],markdown:'# Recovered'});
  throw new Error('Unexpected endpoint '+url);
 });
 render(<App/>);
 await user.type(screen.getByLabelText('Access token'),'x'.repeat(32));
 await user.click(screen.getByRole('button',{name:/Open workspace/}));
 await user.click(await screen.findByRole('button',{name:run.question}));
 await screen.findByText('Network connection lost');
 await user.click(screen.getByRole('button',{name:'Reconnect to run'}));
 await screen.findByText('Recovered saved report');
 expect(streams).toBe(2);
 expect(fetcher.mock.calls.some(([,opts])=>opts?.method==='POST')).toBe(false);
 expect(screen.queryByRole('button',{name:'Reconnect to run'})).toBeNull();
});
test('late report cannot replace the newly selected run',async()=>{
 const user=userEvent.setup();let releaseOld;
 const oldReport=new Promise(resolve=>{releaseOld=resolve});
 const runs=[{id:'old',question:'Old research question',status:'completed'},{id:'new',question:'New research question',status:'completed'}];
 const report=summary=>({summary,outdated_sources:[],citations:[],limitations:[],markdown:summary});
 const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async(url)=>{
  if(url==='/session')return reply({username:'researcher'});
  if(url==='/projects')return reply([project]);
  if(url.endsWith('/sources'))return reply([]);
  if(url.endsWith('/runs'))return reply(runs);
  if(url.endsWith('/stream'))return new Response('event: done\ndata: {"status":"completed"}\n\n');
  if(url.endsWith('/old/report'))return oldReport;
  if(url.endsWith('/new/report'))return reply(report('Correct new report'));
  return reply(runs.find(run=>url.endsWith('/'+run.id)));
 });
 render(<App/>);
 await user.type(screen.getByLabelText('Access token'),'x'.repeat(32));
 await user.click(screen.getByRole('button',{name:/Open workspace/}));
 await user.click(await screen.findByRole('button',{name:runs[0].question}));
 await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.endsWith('/old/report'))).toBe(true));
 await user.click(screen.getByRole('button',{name:runs[1].question}));
 await screen.findByText('Correct new report');
 await act(async()=>{releaseOld(reply(report('Stale old report')));await oldReport});
 expect(screen.getByText('Correct new report')).toBeTruthy();
 expect(screen.queryByText('Stale old report')).toBeNull();
});
test('workspace saves source and retains report on repeated history click',async()=>{
 const user=userEvent.setup();let source=null;
 const run={id:'r',question:'Humidity coating stability',status:'completed'};
 const report={question:run.question,summary:'Review required.',outdated_sources:[],citations:[],limitations:['No calibrated confidence'],markdown:'# Report',collection:{status:'partial',metadata_records:1,fulltext_stored:0,bounded:false,scope:'Absence of results is not evidence against a hypothesis.',errors:[{stage:'fulltext',message:'Full text unavailable'}],queries:[{strategy:'primary_evidence',query:'humidity'}]}};
 const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async(url,options={})=>{
  if(url==='/session')return reply({username:'researcher'});
  if(url==='/projects')return reply([project]);
  if(url.endsWith('/sources')){if(options.method==='POST')source={...JSON.parse(options.body),id:'s',origin:'user_supplied',status:'active'};return reply(options.method==='POST'?source:source?[source]:[])}
  if(url.endsWith('/runs'))return reply([run]);
  if(url.endsWith('/stream'))return new Response('event: done\ndata: {"status":"completed"}\n\n');
  if(url.endsWith('/report'))return reply(report);
  if(url.endsWith('/runs/r'))return reply(run);
  throw new Error('Unexpected endpoint '+url);
 });
 render(<App/>);
 await user.type(screen.getByLabelText('Access token'),'x'.repeat(32));
 await user.click(screen.getByRole('button',{name:/Open workspace/}));
 await screen.findByRole('button',{name:/Humidity coating stability/});
 await user.click(screen.getByRole('button',{name:/Add source/}));
 await user.type(screen.getByLabelText('Title'),'Coating experiment');
 await user.type(screen.getByLabelText('Source URL or reference'),'https://example.org/study');
 await user.type(screen.getByLabelText('License or permission'),'Own observations');
 await user.type(screen.getByLabelText('Source text'),'Humidity affected the coating stability.');
 await user.click(screen.getByRole('button',{name:'Save source'}));
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
 expect(source.text).toContain('Humidity');
 await user.click(screen.getByRole('button',{name:/Humidity coating stability/}));
 await screen.findByText('Review required.');
 expect(screen.getByText('fulltext: Full text unavailable')).toBeTruthy();
 expect(screen.getByText(/Status: partial/)).toBeTruthy();
 await user.click(screen.getByRole('button',{name:/Humidity coating stability/}));
 expect(screen.getByText('Review required.')).toBeTruthy();
 expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/stream'))).toHaveLength(1);
 expect(localStorage.length).toBe(0);
});
test('hypothesis form records mechanism and falsification',async()=>{
 const user=userEvent.setup();let saved;
 const api=vi.fn(async(path,options={})=>{if(options.method==='POST'){saved=JSON.parse(options.body);return {id:'h'}};return []});
 render(<Evidence api={api} project={project} sources={[]}/>);
 await user.click(screen.getByRole('button',{name:'Propose hypothesis'}));
 await user.type(screen.getByLabelText('Statement'),'Humidity weakens this coating');
 await user.type(screen.getByLabelText('Proposed mechanism'),'Water absorption changes the polymer');
 await user.type(screen.getByLabelText('Observation that would falsify it'),'No measurable effect in controlled trials');
 await user.click(screen.getByRole('button',{name:'Save hypothesis'}));
 await waitFor(()=>expect(saved?.predecessor).toBeNull());
 expect(saved.mechanism).toBe('Water absorption changes the polymer');
});
test('dialog errors are visible and Escape closes it',async()=>{
 const user=userEvent.setup();
 vi.spyOn(globalThis,'fetch').mockImplementation(async(url,opts={})=>{
  if(url==='/session')return reply({username:'researcher'});
  if(url==='/projects')return reply([project]);
  if(opts.method==='POST')return new Response(JSON.stringify({detail:'Permission denied'}),{status:403});
  return reply([]);
 });
 render(<App/>);await user.type(screen.getByLabelText('Access token'),'x'.repeat(32));await user.click(screen.getByRole('button',{name:/Open workspace/}));
 await waitFor(()=>expect(screen.queryByLabelText('Access token')).toBeNull());
 await user.click(screen.getByRole('button',{name:/Calculations/}));
 await user.type(screen.getByLabelText('Values, separated by commas'),'1,2,3');await user.click(screen.getByRole('button',{name:'Calculate'}));
 await waitFor(()=>expect(screen.getByRole('dialog').textContent).toContain('Permission denied'));
 await user.keyboard('{Escape}');expect(screen.queryByRole('dialog')).toBeNull();
});
