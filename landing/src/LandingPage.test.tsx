// @vitest-environment jsdom
import React, {act} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach, expect, it} from 'vitest';
import {ScrollTrigger} from 'gsap/ScrollTrigger';
import LandingPage from './LandingPage';
import './style.css';

let root: ReturnType<typeof createRoot> | undefined;
let host: HTMLElement | undefined;

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  host = undefined;
  ScrollTrigger.getAll().forEach(trigger => trigger.kill());
});

it('keeps the landing readable and unpinned when reduced motion is requested', async () => {
  (globalThis as {IS_REACT_ACT_ENVIRONMENT?: boolean}).IS_REACT_ACT_ENVIRONMENT = true;
  Object.defineProperty(window, 'matchMedia', {configurable: true, value: (query: string) => ({
    matches: query.includes('min-width: 1000px') || query.includes('prefers-reduced-motion: reduce'),
    media: query, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {},
  })});
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(<LandingPage />));
  expect(host.querySelector('h1')?.textContent).toContain('More possibility');
  expect(host.querySelectorAll('.landing-flow-step')).toHaveLength(4);
  expect(host.querySelectorAll('.landing-concept')).toHaveLength(7);
  expect(host.querySelector('.pin-spacer')).toBeNull();
  expect(ScrollTrigger.getAll()).toHaveLength(0);
});

