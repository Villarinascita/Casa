import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import { toInstant } from '../js/dates.js';

function setup(values = {}) {
  const fields = Object.fromEntries(Object.entries({
    type: 'event', title: 'Nuoto', member_id: '', notes: '', location: '',
    date: '2026-09-29', start: '18:00', end: '19:00',
    event_repeat: 'weekly', repeat_until: '2026-10-20', reminder_minutes: '60', ...values,
  }).map(([key, value]) => [key, { value }]));
  fields.all_day = { checked: false };
  const context = vm.createContext({ $: () => ({ elements: fields }), toInstant });
  const source = readFileSync(new URL('../js/editor.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/gm, '').replace(/^export /gm, '');
  vm.runInContext(source, context);
  return { fields, context };
}

test('new recurring appointment submits the frequency, final date and reminder', () => {
  const { context } = setup();
  const result = context.payload();
  assert.equal(result.error, undefined);
  assert.equal(result.data.repeat, 'weekly');
  assert.equal(result.data.repeat_until, '2026-10-20');
  assert.equal(result.data.reminder_minutes, 60);
});

test('recurrence requires an end date on or after the first appointment', () => {
  for (const until of ['', '2026-09-28']) {
    const { context } = setup({ repeat_until: until });
    assert.ok(context.payload().error);
  }
});

test('editing one occurrence never submits a new recurrence', () => {
  const { context } = setup();
  vm.runInContext('editing = { id: "existing-occurrence" };', context);
  const result = context.payload();
  assert.equal(result.data.repeat, undefined);
  assert.equal(result.data.repeat_until, undefined);
  assert.equal(result.data.reminder_minutes, 60);
});

test('all-day appointments support reminders and no-repeat clears recurrence', () => {
  const { context, fields } = setup({ event_repeat: '', reminder_minutes: '0' });
  fields.all_day.checked = true;
  const result = context.payload();
  assert.equal(result.data.start_date, '2026-09-29');
  assert.equal(result.data.reminder_minutes, 0);
  assert.equal(result.data.repeat, undefined);
  fields.reminder_minutes.value = '';
  assert.equal(context.payload().data.reminder_minutes, null);
});
