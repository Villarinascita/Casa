import { html } from '../dom.js';
import { addDays, eventOnDay, formatDay, today } from '../dates.js';
import { state } from '../store.js';
import { empty, eventRow, heading, list, sectionHead, taskRow } from './common.js';

function greeting() {
  const hour = new Date().getHours();
  if (hour < 13) return 'Buongiorno.';
  if (hour < 18) return 'Buon pomeriggio.';
  return 'Buonasera.';
}

const tile = (value, label, href, warn = false) =>
  html`<a class="tile ${warn && value ? 'warn' : ''}" href="${href}"><strong>${value}</strong><span>${label}</span></a>`;

export function render() {
  const day = today();
  const todays = state.events.filter((e) => eventOnDay(e, day));
  const open = state.tasks.filter((t) => t.status === 'open');
  const overdue = open.filter((t) => t.due_date && t.due_date < day);
  const dueToday = open.filter((t) => t.due_date === day);
  const noDate = open.filter((t) => !t.due_date);
  const focus = [...overdue, ...dueToday, ...noDate].slice(0, 6);
  const toBuy = state.shopping.filter((s) => !s.checked).length;
  const nextDays = Array.from({ length: 7 }, (_, i) => addDays(day, i + 1))
    .map((d) => ({ day: d, events: state.events.filter((e) => eventOnDay(e, d)) }))
    .filter((d) => d.events.length);

  return html`
    ${heading('Il vostro tempo, insieme', greeting(), 'La giornata della famiglia: impegni, responsabilità e piccole cose da fare.')}
    <div class="tiles">
      ${tile(todays.length, todays.length === 1 ? 'appuntamento oggi' : 'appuntamenti oggi', '#calendario')}
      ${tile(open.length, open.length === 1 ? 'attività aperta' : 'attività aperte', '#attivita')}
      ${tile(overdue.length, overdue.length === 1 ? 'attività scaduta' : 'attività scadute', '#attivita', true)}
      ${tile(toBuy, toBuy === 1 ? 'prodotto da comprare' : 'prodotti da comprare', '#spesa')}
    </div>
    <div class="columns">
      <section>
        ${sectionHead('La giornata', html`<button type="button" data-action="add" data-type="event" data-date="${day}">＋ Appuntamento</button>`)}
        ${list(todays, (e) => eventRow(e), 'Nessun appuntamento per oggi.')}
      </section>
      <section>
        ${sectionHead('Da fare', html`<a href="#attivita">Tutte →</a>`)}
        ${list(focus, taskRow, 'Nessuna attività urgente. Puoi aggiungerne una con «Aggiungi».')}
      </section>
    </div>
    <section class="upcoming">
      ${sectionHead('Prossimi 7 giorni', html`<a href="#calendario">Calendario →</a>`)}
      ${nextDays.length
        ? nextDays.map((d) => html`<h3>${formatDay(d.day, { weekday: 'long', day: 'numeric', month: 'long' })}</h3>${d.events.map((e) => eventRow(e))}`)
        : empty('Nessun appuntamento nei prossimi giorni.')}
    </section>`;
}
