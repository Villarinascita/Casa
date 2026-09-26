import { html } from '../dom.js';
import { addDays, eventOnDay, formatDay, timeOf, today } from '../dates.js';
import { reviewCount, state } from '../store.js';
import { empty, eventRow, heading, sectionHead, taskRow } from './common.js';

const DEADLINE_DAYS = 7;

function greeting() {
  const hour = new Date().getHours();
  const name = state.me?.login ? `, ${state.me.login[0].toUpperCase()}${state.me.login.slice(1)}` : '';
  if (hour < 13) return `Buongiorno${name}.`;
  if (hour < 18) return `Buon pomeriggio${name}.`;
  return `Buonasera${name}.`;
}

const euro = (value) => `${Number(value).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

/** Costi non pagati in scadenza entro 7 giorni (scaduti compresi) e attività aperte scadute o di oggi. */
export function deadlines(day, bills, tasks) {
  const limit = addDays(day, DEADLINE_DAYS);
  const dueBills = bills.filter((b) => b.payment_state !== 'pagato' && b.due_date && b.due_date <= limit)
    .map((bill) => ({ kind: 'bill', date: bill.due_date, item: bill }));
  const dueTasks = tasks.filter((t) => t.status === 'open' && t.due_date && t.due_date <= day)
    .map((task) => ({ kind: 'task', date: task.due_date, item: task }));
  return [...dueBills, ...dueTasks].sort((a, b) => a.date.localeCompare(b.date));
}

export const weekTotal = (entries) => entries
  .filter((e) => e.kind === 'bill' && e.item.amount !== null)
  .reduce((sum, e) => sum + Number(e.item.amount), 0);

function whenLabel(date, day) {
  if (date < day) {
    const days = Math.round((new Date(day) - new Date(date)) / 86_400_000);
    return days === 1 ? 'Scaduto ieri' : `Scaduto da ${days} giorni`;
  }
  if (date === day) return 'Oggi';
  if (date === addDays(day, 1)) return 'Domani';
  return formatDay(date, { weekday: 'long' });
}

function deadlineRow({ kind, date, item }, day) {
  const late = date < day;
  if (kind === 'task') return taskRow(item);
  return html`<div class="item deadline ${late ? 'late' : ''}">
    <button type="button" class="item-open" data-action="edit" data-kind="bill" data-id="${item.id}">
      <span class="item-title">${item.title}</span>
      <span class="meta">${[whenLabel(date, day), item.supplier].filter(Boolean).join(' · ')}</span>
    </button>
    <strong class="amount">${item.amount === null ? '—' : euro(item.amount)}</strong>
  </div>`;
}

/** Appuntamenti di oggi con una linea «ORA» tra quelli già finiti e i successivi. */
function todayEvents(events) {
  const now = new Date();
  const ended = (e) => !e.all_day && new Date(e.end_at || e.start_at) < now;
  const past = events.filter(ended);
  const next = events.filter((e) => !ended(e));
  const nowLine = html`<div class="now-line" role="separator"><span>ORA ${timeOf(now.toISOString())}</span></div>`;
  return html`${past.map((e) => html`<div class="past">${eventRow(e)}</div>`)}${past.length && next.length ? nowLine : ''}${next.map((e) => eventRow(e))}`;
}

function reviewBanner() {
  const count = reviewCount();
  if (!count) return '';
  const parts = [state.review.proposals && `${state.review.proposals} dalle email`,
    state.review.conflicts && `${state.review.conflicts} ${state.review.conflicts === 1 ? 'conflitto' : 'conflitti'} del calendario`];
  return html`<a class="review-banner" href="#controllare">
    <span class="review-count">${count}</span>
    <span class="review-text"><strong>Da controllare</strong><span>${parts.filter(Boolean).join(' · ')}</span></span>
    <span aria-hidden="true">→</span>
  </a>`;
}

export function render() {
  const day = today();
  const todays = state.events.filter((e) => eventOnDay(e, day));
  const due = deadlines(day, state.bills, state.tasks);
  const total = weekTotal(due);
  const open = state.tasks.filter((t) => t.status === 'open' && (!t.due_date || t.due_date > day));
  const toBuy = state.shopping.filter((s) => !s.checked).length;
  const tomorrow = state.events.find((e) => eventOnDay(e, addDays(day, 1)));

  return html`
    ${heading('Il vostro tempo, insieme', greeting(), '')}
    ${reviewBanner()}
    <div class="today-grid">
      <section class="panel">
        ${sectionHead('Oggi', html`<button type="button" data-action="add" data-type="event" data-date="${day}" aria-label="Nuovo appuntamento oggi">＋ Nuovo</button>`)}
        ${todays.length ? todayEvents(todays) : empty('Nessun appuntamento per oggi.')}
      </section>
      <section class="panel">
        ${sectionHead('Scadenze', html`<span class="head-note">prossimi ${DEADLINE_DAYS} giorni</span>`)}
        ${due.length ? due.map((entry) => deadlineRow(entry, day)) : empty('Niente in scadenza. Bene così.')}
        ${total ? html`<a class="week-total" href="#archivio">Da pagare entro ${DEADLINE_DAYS} giorni: <strong>${euro(total)}</strong> →</a>` : ''}
      </section>
      <section class="panel">
        ${sectionHead('Da fare', html`<a href="#attivita">Tutte →</a>`)}
        ${open.length ? open.slice(0, 5).map(taskRow) : empty('Nessuna attività aperta. Puoi aggiungerne una con «+».')}
      </section>
      <div class="mini-tiles">
        <a class="mini-tile shopping" href="#spesa"><strong>${toBuy}</strong><span>${toBuy === 1 ? 'prodotto da comprare' : 'prodotti da comprare'}</span></a>
        <a class="mini-tile tomorrow" href="#calendario"><strong>Domani${tomorrow && !tomorrow.all_day ? ` ${timeOf(tomorrow.start_at)}` : ''}</strong><span>${tomorrow ? tomorrow.title : 'Nessun appuntamento'}</span></a>
      </div>
    </div>`;
}
