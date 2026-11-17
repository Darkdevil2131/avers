// @vitest-environment happy-dom
import React from 'react';
import {afterEach, beforeEach, expect, test, vi} from 'vitest';
import {act, cleanup, render, screen} from '@testing-library/react';
import RuntimeStatus from './RuntimeStatus';

beforeEach(() => vi.useFakeTimers());
afterEach(() => {cleanup(); vi.useRealTimers(); vi.restoreAllMocks();});
const reply = data => ({ok: true, json: async () => data});

test('polls authenticated status and shows a disconnected worker after connection is lost', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(reply({database:'connected', worker:'connected', reasoning:['configured']}))
    .mockResolvedValue(reply({database:'connected', worker:'stale', reasoning:[]}));
  await act(async () => render(<RuntimeStatus token="private-token"/>));
  expect(fetch).toHaveBeenCalledWith('/runtime', expect.objectContaining({headers:{Authorization:'Bearer private-token'}}));
  expect(screen.getByText(/Research worker heartbeat received/)).toBeTruthy();
  expect(screen.getByText(/Inference results appear in each report/)).toBeTruthy();
  await act(async () => vi.advanceTimersByTimeAsync(10000));
  expect(screen.getByText(/no recent research worker heartbeat/)).toBeTruthy();
  expect(screen.queryByText(/Local model configured/)).toBeNull();
});

test('failed and timed-out requests clear a previously connected status', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(reply({database:'connected', worker:'connected'}))
    .mockImplementation((_url, {signal}) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('Aborted')));
    }));
  await act(async () => render(<RuntimeStatus token="token"/>));
  await act(async () => vi.advanceTimersByTimeAsync(18000));
  expect(screen.getByText(/Server status unavailable/)).toBeTruthy();
  expect(screen.queryByText(/heartbeat received/)).toBeNull();
});

test('inline mode discloses missing model and unmount stops polling', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply({
    database:'connected', worker:'in_process', reasoning:['not_configured'],
  }));
  let rendered;
  await act(async () => {rendered = render(<RuntimeStatus token="token"/>);});
  expect(screen.getByText(/Research runs inside the API process/)).toBeTruthy();
  expect(screen.getByText(/Local model unavailable/)).toBeTruthy();
  rendered.unmount();
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(fetch).toHaveBeenCalledTimes(1);
});
