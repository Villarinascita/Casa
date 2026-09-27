// La settimana dei nonni: unica pagina per gli accessi «nonno». Scritte grandi, niente menu.

import { $, $$, html } from '../dom.js';
import { api } from '../api.js';
import { addDays, parseDate, today } from '../dates.js';
import { openEditor } from '../editor.js';
import { logout, state } from '../store.js';

const REFRESH_MS = 60_000;
let week = null;
let start = null;
let error = null;
let timer = null;

const longDate = (iso) => parseDate(iso).toLocaleDateString('it-IT', { day: 'numeric', month: 'long' });

function item(it) {
  return html`<li class="nonni-item">
    <span class="nonni-time ${it.time ? '' : 'later'}">${it.time || 'Poi'}</span>
    <span class="nonni-what">${it.title}</span>
    ${it.place ? html`<span class="nonni-detail">Dove: ${it.place}</span>` : ''}
    ${it.notes ? html`<span class="nonni-detail">${it.notes}</span>` : ''}
    ${week.who.length > 1 && it.who ? html`<span class="nonni-who">${it.who}</span>` : ''}
    ${state.me?.role !== 'nonno' && it.id ? html`<button type="button" class="nonni-edit" data-edit="${it.id}" data-kind="${it.kind}">Modifica</button>` : ''}
  </li>`;
}

function day(d) {
  const isToday = d.date === week.today;
  const past = d.date < week.today;
  return html`<section class="nonni-day ${isToday ? 'today' : ''} ${past ? 'past' : ''}" aria-label="${d.name} ${longDate(d.date)}">
    <h2>${isToday ? html`<span class="nonni-badge">OGGI</span>` : ''}${d.name} <span>${longDate(d.date)}</span></h2>
    ${d.items.length ? html`<ul>${d.items.map(item)}</ul>` : html`<p class="nonni-free">Niente da fare</p>`}
  </section>`;
}

export function render() {
  let body;
  if (error) body = html`<p class="nonni-free">${error}</p><button type="button" class="nonni-nav" data-week="reload">Riprova</button>`;
  else if (!week) body = html`<p class="nonni-free">Un attimo…</p>`;
  else {
    // La settimana in corso parte da oggi: i giorni già passati non servono.
    const days = week.start <= week.today && week.today <= addDays(week.start, 6)
      ? week.days.filter((d) => d.date >= week.today) : week.days;
    body = html`${days.map(day)}`;
  }
  const current = week && week.start <= week.today && week.today <= addDays(week.start, 6);
  return html`<div class="nonni">
    <div class="nonni-head">
      <h1 tabindex="-1">${current || !week ? 'Questa settimana' : `Settimana dal ${longDate(week.start)}`}</h1>
    </div>
    <div class="nonni-list">${body}</div>
    <nav class="nonni-bar" aria-label="Settimane">
      <button type="button" class="nonni-nav" data-week="prev" ${current ? 'hidden' : ''}>◀ Indietro</button>
      ${current ? '' : html`<button type="button" class="nonni-nav" data-week="today">Torna a oggi</button>`}
      <button type="button" class="nonni-nav" data-week="next">Settimana dopo ▶</button>
    </nav>
    ${state.me?.role === 'nonno'
      ? html`<p class="nonni-foot">Accesso come ${state.me?.login}. <button type="button" class="nonni-exit">Esci</button></p>`
      : html`<p class="nonni-foot">Questa è l'anteprima di ciò che vedono i nonni. <a href="#impostazioni">Torna alle Impostazioni</a></p>`}
  </div>`;
}

async function load(rerender) {
  try {
    week = await api('GET', `/nonni/week${start ? `?start=${start}` : ''}`);
    error = null;
  } catch (err) {
    error = err.message;
  }
  rerender();
}

export function mount(root) {
  const rerender = () => {
    if (!root.isConnected) return;
    root.innerHTML = String(render());
    bind(root, rerender);
  };
  bind(root, rerender);
  // L'anteprima si ricarica a ogni apertura (anche dopo una modifica); i nonni ogni minuto.
  load(rerender);
  clearInterval(timer);
  timer = setInterval(() => { if (document.visibilityState === 'visible') load(rerender); }, REFRESH_MS);
}

function bind(root, rerender) {
  $$('[data-week]', root).forEach((button) => button.addEventListener('click', () => {
    const action = button.dataset.week;
    if (action === 'next') start = addDays((week?.start) || today(), 7);
    else if (action === 'prev') start = addDays((week?.start) || today(), -7);
    else start = null;
    week = null;
    rerender();
    load(rerender);
    window.scrollTo(0, 0);
  }));
  $('.nonni-exit', root)?.addEventListener('click', () => { clearInterval(timer); logout(); });
  $$('[data-edit]', root).forEach((button) => button.addEventListener('click', async () => {
    const { edit, kind } = button.dataset;
    try {
      const entity = await api('GET', `/${kind === 'event' ? 'events' : 'tasks'}/${edit}`);
      openEditor({ type: kind, entity });
    } catch (err) { button.textContent = err.message; }
  }));
}
