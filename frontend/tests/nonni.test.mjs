import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

// Run the real view with controlled network responses and browser timers.
function setup() {
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  const context = vm.createContext({
    $: () => null, $$: () => [],
    html: (parts, ...values) => parts.reduce((s, p, i) => s + p + (values[i] ?? ''), ''),
    api: () => new Promise((resolve, reject) => requests.push({ resolve, reject })),
    addDays: () => '2026-10-04', parseDate: (s) => new Date(s), today: () => '2026-09-29',
    state: { me: { role: 'adult' } }, location: { hash: '#nonni' },
    document: { visibilityState: 'visible' },
    setInterval: (fn) => { timers.set(++timerId, fn); return timerId; },
    clearInterval: (id) => timers.delete(id),
    logout() {}, openEditor() {},
  });
  const source = readFileSync(new URL('../js/views/nonni.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  vm.runInContext(source, context);
  const root = { isConnected: true, innerHTML: 'pagina iniziale' };
  const cleanup = context.mount(root);
  const week = { start: '2026-09-28', today: '2026-09-29', days: [], who: [] };
  return { context, root, cleanup, requests, timers, week };
}

test('a late response cannot replace the page selected after leaving the preview', async () => {
  const s = setup();
  s.context.location.hash = '#calendario';
  s.root.innerHTML = 'Calendario';
  s.cleanup?.();
  s.requests[0].resolve(s.week);
  await new Promise(setImmediate);
  assert.equal(s.root.innerHTML, 'Calendario');
  assert.equal(s.timers.size, 0);
});

test('a late error after logout cannot replace the login page', async () => {
  const s = setup();
  s.context.state.me = null;
  s.root.innerHTML = 'Accedi';
  s.cleanup?.();
  s.requests[0].reject(new Error('Server non disponibile'));
  await new Promise(setImmediate);
  assert.equal(s.root.innerHTML, 'Accedi');
});

test('grandparent accounts refresh their page even without the preview hash', async () => {
  const s = setup();
  s.context.state.me.role = 'nonno';
  s.context.location.hash = '';
  s.requests[0].resolve(s.week);
  await new Promise(setImmediate);
  assert.match(s.root.innerHTML, /Questa settimana/);
  assert.equal(s.timers.size, 1);
  s.cleanup?.();
});

test('leaving the preview stops periodic requests even before the next render', () => {
  const s = setup();
  s.context.location.hash = '#oggi';
  for (const tick of s.timers.values()) tick();
  assert.equal(s.requests.length, 1);
  assert.equal(s.timers.size, 0);
});

test('a previous visit cannot overwrite the current visit with an old error', async () => {
  const s = setup();
  s.cleanup?.();
  const cleanup = s.context.mount(s.root);
  s.requests[1].resolve(s.week);
  await new Promise(setImmediate);
  const currentPage = s.root.innerHTML;
  s.requests[0].reject(new Error('Errore della visita precedente'));
  await new Promise(setImmediate);
  assert.equal(s.root.innerHTML, currentPage);
  assert.equal(s.timers.size, 1);
  cleanup?.();
});
