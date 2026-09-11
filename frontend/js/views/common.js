import { html } from '../dom.js';
import { eventSpan, eventTimeLabel, formatDay, today } from '../dates.js';
import { memberById } from '../store.js';

export const heading = (eyebrow, title, intro) =>
  html`<div class="eyebrow">${eyebrow}</div><h1 tabindex="-1">${title}</h1>${intro ? html`<p class="intro">${intro}</p>` : ''}`;

export const empty = (text) => html`<p class="empty">${text}</p>`;

export const list = (items, row, emptyText) => (items.length ? items.map(row) : empty(emptyText));

const meta = (parts) => html`<span class="meta">${parts.filter(Boolean).map((p, i) => html`${i ? ' · ' : ''}${p}`)}</span>`;

function openButton(kind, id, title, metaParts) {
  return html`<button type="button" class="item-open" data-action="edit" data-kind="${kind}" data-id="${id}">
    <span class="item-title">${title}</span>${meta(metaParts)}</button>`;
}

const deleteButton = (kind, id, title) =>
  html`<button type="button" class="delete" data-action="delete" data-kind="${kind}" data-id="${id}" aria-label="Elimina ${title}">Elimina</button>`;

const memberName = (id) => memberById(id)?.display_name || null;

export function eventRow(event, { showDate = false } = {}) {
  const [first, last] = eventSpan(event);
  const dateLabel = showDate ? (first === last ? formatDay(first) : `${formatDay(first)} → ${formatDay(last)}`) : null;
  return html`<div class="item">
    <span class="time-pill ${event.all_day ? 'all-day' : ''}">${eventTimeLabel(event)}</span>
    ${openButton('event', event.id, event.title, [dateLabel, memberName(event.member_id) || 'Nessuno assegnato', event.location])}
    ${deleteButton('event', event.id, event.title)}
  </div>`;
}

function dueLabel(task) {
  if (!task.due_date) return null;
  const day = today();
  if (task.status === 'open' && task.due_date < day) return html`<span class="badge warn">Scaduta ${formatDay(task.due_date)}</span>`;
  if (task.due_date === day) return 'Oggi';
  return `Entro ${formatDay(task.due_date)}`;
}

export function taskRow(task) {
  const done = task.status === 'done';
  return html`<div class="item ${done ? 'done' : ''}">
    <button type="button" class="check" data-action="toggle" data-kind="task" data-id="${task.id}"
      aria-pressed="${done}" aria-label="${done ? 'Riapri' : 'Completa'} ${task.title}">${done ? '✓' : ''}</button>
    ${openButton('task', task.id, task.title, [dueLabel(task), memberName(task.member_id) || 'Da assegnare', task.notes])}
    ${deleteButton('task', task.id, task.title)}
  </div>`;
}

export function shoppingRow(item) {
  return html`<div class="item ${item.checked ? 'done' : ''}">
    <button type="button" class="check" data-action="toggle" data-kind="shopping" data-id="${item.id}"
      aria-pressed="${item.checked}" aria-label="${item.checked ? 'Rimetti in lista' : 'Spunta'} ${item.label}">${item.checked ? '✓' : ''}</button>
    ${openButton('shopping', item.id, item.label, [item.quantity])}
    ${deleteButton('shopping', item.id, item.label)}
  </div>`;
}

export const sectionHead = (title, extra = '') => html`<div class="section-head"><h2>${title}</h2>${extra}</div>`;
