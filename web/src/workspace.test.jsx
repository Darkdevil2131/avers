// @vitest-environment happy-dom
import React from 'react';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import {cleanup, render, screen, waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
vi.mock('./Scene',()=>({default:()=> <div>Source graph</div>}));
import {App} from './main';
import Evidence from './Evidence';
afterEach(()=>{cleanup();vi.restoreAllMocks()});
beforeEach(()=>{window.matchMedia=vi.fn(()=>({matches:true}));});
const project={id:'p',name:'Coatings',role:'owner'};
const reply=data=>new Response(JSON.stringify(data),{headers:{'Content-Type':'application/json'}});
test('workspace saves source and retains report on repeated history click',async()=>{
 const user=userEvent.setup();let source=null;
 const run={id:'r',question:'Humidity coating stability',status:'completed'};
 const report={question:run.question,summary:'Review required.',outdated_sources:[],citations:[],limitations:['No calibrated confidence'],markdown:'# Report'};
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
