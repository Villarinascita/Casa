import { html } from '../dom.js';
import { eventOnDay, formatDay, localDate, timeOf, today } from '../dates.js';
import { state } from '../store.js';
import { eventRow, heading, list, sectionHead, taskRow } from './common.js';

const WEEKDAYS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];
const MAX_IN_CELL = 3;

let month = new Date();
month.setDate(1);
let selected = null;

function dayCell(date, number) {
  const events = state.events.filter((e) => eventOnDay(e, date));
  const classes = ['day', date === today() ? 'today' : '', date === selected ? 'selected' : ''].join(' ');
  const label = `${formatDay(date, { weekday: 'long', day: 'numeric', month: 'long' })}: ${events.length ? `${events.length} appuntamenti` : 'nessun appuntamento'}`;
  return html`<button type="button" class="${classes}" data-action="select-day" data-day="${date}" aria-label="${label}" aria-pressed="${date === selected}">
    <span class="num">${number}</span>
    ${events.slice(0, MAX_IN_CELL).map((e) => html`<small>${e.all_day ? '' : `${timeOf(e.start_at)} `}${e.title}</small>`)}
    ${events.length > MAX_IN_CELL ? html`<small class="more">+${events.length - MAX_IN_CELL} altri</small>` : ''}
  </button>`;
}

function detail(year, m) {
  if (selected) {
    const events = state.events.filter((e) => eventOnDay(e, selected));
    const tasks = state.tasks.filter((t) => t.due_date === selected);
    return html`
      ${sectionHead(formatDay(selected, { weekday: 'long', day: 'numeric', month: 'long' }),
        html`<button type="button" class="primary" data-action="add" data-type="event" data-date="${selected}">＋ Aggiungi in questo giorno</button>`)}
      ${list(events, (e) => eventRow(e), 'Nessun appuntamento in questo giorno.')}
      ${tasks.length ? html`<h3>Scadenze</h3>${tasks.map(taskRow)}` : ''}`;
  }
  const prefix = `${year}-${String(m + 1).padStart(2, '0')}`;
  const events = state.events.filter((e) => (e.all_day ? e.start_date : localDate(new Date(e.start_at))).startsWith(prefix));
  return html`${sectionHead('Appuntamenti del mese')}${list(events, (e) => eventRow(e, { showDate: true }), 'Ancora nessun appuntamento questo mese.')}`;
}

export function render() {
  const year = month.getFullYear();
  const m = month.getMonth();
  const offset = (new Date(year, m, 1).getDay() + 6) % 7;
  const days = new Date(year, m + 1, 0).getDate();
  const title = month.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' });
  return html`
    ${heading('Organizzazione familiare', 'Il calendario.', 'Tocca un giorno per vederne gli impegni o aggiungerne uno.')}
    <div class="month-nav">
      <button type="button" data-action="month" data-step="-1" aria-label="Mese precedente">←</button>
      <h2 aria-live="polite">${title}</h2>
      <button type="button" data-action="month" data-step="1" aria-label="Mese successivo">→</button>
      <button type="button" data-action="month" data-step="0">Oggi</button>
    </div>
    <div class="calendar">
      ${WEEKDAYS.map((d) => html`<div class="weekday" aria-hidden="true">${d}</div>`)}
      ${Array.from({ length: offset }, () => html`<div class="day blank"></div>`)}
      ${Array.from({ length: days }, (_, n) => dayCell(localDate(new Date(year, m, n + 1)), n + 1))}
    </div>
    ${detail(year, m)}`;
}

export function onAction(el, rerender) {
  const { action } = el.dataset;
  if (action === 'month') {
    const step = Number(el.dataset.step);
    if (step === 0) {
      month = new Date();
      selected = today();
    } else {
      month.setMonth(month.getMonth() + step);
      selected = null;
    }
    month.setDate(1);
    rerender();
    return true;
  }
  if (action === 'select-day') {
    selected = selected === el.dataset.day ? null : el.dataset.day;
    rerender();
    return true;
  }
  return false;
}
