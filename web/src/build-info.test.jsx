// @vitest-environment happy-dom
import React from 'react';
import {afterEach,expect,test} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import BuildInfo from './BuildInfo';
afterEach(cleanup);
test('matching labels do not claim latest deployment',()=>{render(<BuildInfo frontend={'a'.repeat(40)} backend={'a'.repeat(40)}/>);expect(screen.getByText('Frontend and backend report the same revision.')).toBeTruthy();expect(screen.getByText(/do not prove this is the latest/)).toBeTruthy()});
test('mismatch is explicit',()=>{render(<BuildInfo frontend={'a'.repeat(40)} backend={'b'.repeat(40)}/>);expect(screen.getByText(/Version mismatch/)).toBeTruthy()});
test('invalid and absent revisions are unknown',()=>{render(<BuildInfo frontend="not-a-revision"/>);expect(screen.getAllByText('unknown')).toHaveLength(2);expect(screen.getByText(/identity is incomplete/)).toBeTruthy()});
