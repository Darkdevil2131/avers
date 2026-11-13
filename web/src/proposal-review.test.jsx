// @vitest-environment happy-dom
import React from 'react';
import {afterEach,expect,test} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import ProposalReview from './ProposalReview';
afterEach(cleanup);

test('negation review remains visible even when the candidate was not rejected',()=>{
  render(<ProposalReview check={{accepted_as_candidate:true,scientific_validation:false,
    direction_check:{status:'requires_review',hypothesis_basis:'negation_requires_context_review',evidence_basis:'explicit_direction_word'},
    limitations:['Matching outcomes have not been checked.']}}/>);
  expect(screen.getByText('Direction comparison needs human review')).toBeTruthy();
  expect(screen.getByText(/Negated wording needs context/)).toBeTruthy();
  expect(screen.getByText(/Passing these rules is not approval/)).toBeTruthy();
  expect(screen.getByText('Matching outcomes have not been checked.')).toBeTruthy();
});

test.each([undefined,{}, {direction_check:{status:'unknown_future_status'}}])('older or unknown reports do not imply a passed check: %j',check=>{
  render(<ProposalReview check={check}/>);
  expect(screen.getByText('Direction check unavailable for this report')).toBeTruthy();
  expect(screen.getByText(/Scientific support has not been validated/)).toBeTruthy();
});

test('no opposition does not appear as scientific approval',()=>{
  render(<ProposalReview check={{direction_check:{status:'no_opposition_detected'}}}/>);
  expect(screen.getByText('No opposing direction detected by the rules')).toBeTruthy();
  expect(screen.getByText(/Scientific support has not been validated/)).toBeTruthy();
});
