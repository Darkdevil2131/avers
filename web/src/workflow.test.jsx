// @vitest-environment happy-dom
import React from 'react';
import {afterEach,expect,test} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import Workflow from './Workflow';
afterEach(cleanup);
test('empty workflow does not invent agent activity',()=>{render(<Workflow/>);expect(screen.getAllByText('Not observed')).toHaveLength(6);expect(screen.queryByText('In progress')).toBeNull()});
test('only a recorded invocation is active',()=>{render(<Workflow run={{status:'running'}} events={[{id:1,stage:'reasoner_started',payload:{}}]}/>);expect(screen.getAllByText('In progress')).toHaveLength(1);expect(screen.getAllByText('Not observed')).toHaveLength(5)});
test('cancellation never leaves a role active',()=>{render(<Workflow run={{status:'cancelled'}} events={[{id:1,stage:'reasoner_started',payload:{}}]}/>);expect(screen.queryByText('In progress')).toBeNull();expect(screen.getAllByText('Not reached')).toHaveLength(5)});
test('model rejection is attention, not success',()=>{render(<Workflow run={{status:'completed'}} events={[{id:1,stage:'reasoner_completed',payload:{status:'rejected',reason:'Invalid model quote'}},{id:2,stage:'hypothesize',payload:{proposals:1,type:'replication candidates'}}]}/>);expect(screen.getByText('Needs attention')).toBeTruthy();expect(screen.getByText('Invalid model quote')).toBeTruthy()});
