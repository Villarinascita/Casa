// Costi di casa: riepilogo per mese e per categoria, elenco del mese scelto.

import { html, toast } from '../dom.js';
import { formatDay, today } from '../dates.js';
import { state, update } from '../store.js';
import { heading } from './common.js';

const PAST_MONTHS = 12;
const NEXT_MONTHS = 3;
const COLORS = ['#8fd0ff', '#f5cf65', '#c8b3ff', '#9ff0d3', '#ffa59a', '#ffc98a', '#b8c4ff', '#f0a6d8'];

let selectedMonth = today().slice(0, 7);
let category = '';

const euro = (value) => `${Number(value).toLocaleString('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const amount = (bill) => (bill.amount === null ? 0 : Number(bill.amount));
/** Il mese di un costo è quello della scadenza; senza scadenza, quello in cui è arrivato. */
export const monthOf = (bill) => (bill.due_date || bill.created_at.slice(0, 10)).slice(0, 7);
const isPaid = (bill) => bill.payment_state === 'pagato';
/** Colori con attributi SVG: la politica di sicurezza del sito vieta gli stili scritti nell'HTML. */
const swatch = (color) => html`<svg class="swatch" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect width="12" height="12" rx="3" fill="${color}"/></svg>`;

function stack(parts, max) {
  let y = 100;
  const rects = parts.map(([value, color]) => {
    const h = (value / max) * 100;
    y -= h;
    return html`<rect x="0" y="${y.toFixed(2)}" width="10" height="${Math.max(h - 0.6, 0.8).toFixed(2)}" rx="1" fill="${color}"/>`;
  });
  return html`<svg class="bar-stack" viewBox="0 0 10 100" preserveAspectRatio="none" aria-hidden="true">${rects}</svg>`;
}

function shiftMonth(month, delta) {
  const [y, m] = month.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

const monthLabel = (month, style = 'short') => new Date(`${month}-01T12:00:00`)
  .toLocaleDateString('it-IT', style === 'short' ? { month: 'short' } : { month: 'long', year: 'numeric' });

export function categoriesOf(bills) {
  const configured = state.household?.bill_categories || [];
  return [...new Set([...configured, ...bills.map((b) => b.category)])];
}

/** Totali per mese e per categoria: { '2026-09': { total, byCategory: { Bollette: 120 } } }. */
export function monthlyTotals(bills, months) {
  const table = Object.fromEntries(months.map((m) => [m, { total: 0, byCategory: {} }]));
  for (const bill of bills) {
    const row = table[monthOf(bill)];
    if (!row) continue;
    row.total += amount(bill);
    row.byCategory[bill.category] = (row.byCategory[bill.category] || 0) + amount(bill);
  }
  return table;
}

function summary(bills, months, totals) {
  const current = today().slice(0, 7);
  const thisMonth = bills.filter((b) => monthOf(b) === current);
  const paid = thisMonth.filter(isPaid).reduce((s, b) => s + amount(b), 0);
  const due = thisMonth.filter((b) => !isPaid(b)).reduce((s, b) => s + amount(b), 0);
  const overdue = bills.filter((b) => !isPaid(b) && b.due_date && b.due_date < today()).reduce((s, b) => s + amount(b), 0);
  const past = months.filter((m) => m <= current).slice(-PAST_MONTHS).filter((m) => totals[m].total > 0);
  const average = past.length ? past.reduce((s, m) => s + totals[m].total, 0) / past.length : 0;
  return html`<div class="cost-summary">
    <div class="cost-stat"><span>Questo mese</span><strong>${euro(paid + due)}</strong><small>${euro(paid)} pagati · ${euro(due)} da pagare</small></div>
    <div class="cost-stat ${overdue ? 'late' : ''}"><span>Scaduti</span><strong>${euro(overdue)}</strong><small>${overdue ? 'da pagare al più presto' : 'nessun ritardo'}</small></div>
    <div class="cost-stat"><span>Media mensile</span><strong>${euro(average)}</strong><small>${past.length ? `su ${past.length} ${past.length === 1 ? 'mese' : 'mesi'} con costi` : 'ancora nessun dato'}</small></div>
  </div>`;
}

function chart(months, totals, cats, colorOf) {
  const max = Math.max(1, ...months.map((m) => totals[m].total));
  const current = today().slice(0, 7);
  return html`<div class="cost-chart" role="group" aria-label="Costi mese per mese">
    ${months.map((m) => html`<button type="button" class="bar ${m === selectedMonth ? 'selected' : ''} ${m > current ? 'future' : ''}"
      data-action="month" data-month="${m}" aria-pressed="${m === selectedMonth}"
      aria-label="${monthLabel(m, 'long')}: ${euro(totals[m].total)}">
      <span class="bar-value">${totals[m].total ? Math.round(totals[m].total) : ''}</span>
      ${stack(cats.filter((c) => totals[m].byCategory[c]).map((c) => [totals[m].byCategory[c], colorOf(c)]), max)}
      <span class="bar-label">${monthLabel(m)}</span>
    </button>`)}
  </div>
  <div class="cost-legend">${cats.map((c) => html`<span>${swatch(colorOf(c))}${c}</span>`)}</div>`;
}

function table(months, totals, cats) {
  const withData = months.filter((m) => totals[m].total > 0);
  if (!withData.length) return '';
  const catTotal = (c) => withData.reduce((s, m) => s + (totals[m].byCategory[c] || 0), 0);
  return html`<details class="cost-table-box" open>
    <summary>Mesi e categorie</summary>
    <div class="cost-table-scroll"><table class="cost-table">
      <thead><tr><th scope="col">Mese</th>${cats.map((c) => html`<th scope="col">${c}</th>`)}<th scope="col">Totale</th></tr></thead>
      <tbody>${withData.map((m) => html`<tr class="${m === selectedMonth ? 'selected' : ''}">
        <th scope="row">${monthLabel(m, 'long')}</th>
        ${cats.map((c) => html`<td>${totals[m].byCategory[c] ? euro(totals[m].byCategory[c]) : '—'}</td>`)}
        <td><strong>${euro(totals[m].total)}</strong></td></tr>`)}</tbody>
      <tfoot><tr><th scope="row">Totale</th>${cats.map((c) => html`<td>${euro(catTotal(c))}</td>`)}
        <td><strong>${euro(withData.reduce((s, m) => s + totals[m].total, 0))}</strong></td></tr></tfoot>
    </table></div>
  </details>`;
}

function billRow(bill, colorOf) {
  const late = !isPaid(bill) && bill.due_date && bill.due_date < today();
  const meta = [bill.category, bill.supplier, bill.due_date ? `${late ? 'scaduta' : 'scade'} ${formatDay(bill.due_date)}` : null,
    bill.payment_state === 'addebito_previsto' ? 'addebito automatico' : null].filter(Boolean).join(' · ');
  return html`<div class="item cost-row ${isPaid(bill) ? 'done' : ''} ${late ? 'late' : ''}" data-bill="${bill.id}">
    ${swatch(colorOf(bill.category))}
    <button type="button" class="item-open" data-action="edit" data-kind="bill" data-id="${bill.id}">
      <span class="item-title">${bill.title}</span><span class="meta">${meta}</span>
    </button>
    <strong class="amount">${bill.amount === null ? '—' : euro(bill.amount)}</strong>
    ${isPaid(bill)
      ? html`<button type="button" class="pay undo" data-action="unpay" aria-label="${bill.title}: rimetti da pagare">Pagato ✓</button>`
      : html`<button type="button" class="pay primary" data-action="pay" aria-label="Segna pagato ${bill.title}">Pagato</button>`}
  </div>`;
}

function monthList(bills, colorOf) {
  const inMonth = bills.filter((b) => monthOf(b) === selectedMonth);
  const groups = [
    ['Scaduti', inMonth.filter((b) => !isPaid(b) && b.due_date && b.due_date < today())],
    ['Da pagare', inMonth.filter((b) => !isPaid(b) && !(b.due_date && b.due_date < today()))],
    ['Pagati', inMonth.filter(isPaid)],
  ];
  const total = inMonth.reduce((s, b) => s + amount(b), 0);
  return html`<section class="panel cost-month">
    <div class="section-head">
      <button type="button" data-action="month" data-month="${shiftMonth(selectedMonth, -1)}" aria-label="Mese precedente">←</button>
      <h2>${monthLabel(selectedMonth, 'long')} · ${euro(total)}</h2>
      <button type="button" data-action="month" data-month="${shiftMonth(selectedMonth, 1)}" aria-label="Mese successivo">→</button>
    </div>
    ${inMonth.length ? groups.filter(([, list]) => list.length).map(([title, list]) => html`
      <h3>${title} · ${euro(list.reduce((s, b) => s + amount(b), 0))}</h3>${list.map((b) => billRow(b, colorOf))}`)
    : html`<p class="empty">Nessun costo in questo mese.</p>`}
  </section>`;
}

export function render() {
  const allCats = categoriesOf(state.bills);
  const colorOf = (c) => COLORS[Math.max(0, allCats.indexOf(c)) % COLORS.length];
  const bills = category ? state.bills.filter((b) => b.category === category) : state.bills;
  const current = today().slice(0, 7);
  const months = Array.from({ length: PAST_MONTHS + NEXT_MONTHS }, (_, i) => shiftMonth(current, i - PAST_MONTHS + 1));
  const totals = monthlyTotals(bills, months);
  const cats = category ? [category] : allCats.filter((c) => bills.some((b) => b.category === c));

  return html`
    ${heading('Le spese di casa', 'Costi.', 'Bollette e costi trovati nelle email, più quelli che aggiungi tu. Il mese di un costo è quello della scadenza.')}
    <div class="cost-toolbar">
      <div class="filter-pills" role="group" aria-label="Categoria">
        <button type="button" data-action="category" data-category="" aria-pressed="${!category}">Tutte</button>
        ${allCats.map((c) => html`<button type="button" data-action="category" data-category="${c}" aria-pressed="${category === c}">${c}</button>`)}
      </div>
      <button type="button" class="primary" data-action="add" data-type="bill">＋ Nuovo costo</button>
    </div>
    ${summary(bills, months, totals)}
    <section class="panel">${chart(months, totals, cats, colorOf)}</section>
    ${monthList(bills, colorOf)}
    ${table(months, totals, cats)}`;
}

/** Selezione di mese e categoria e pulsante «Pagato»; apertura della scheda e «+» li gestisce main.js. */
export function onAction(el, rerender) {
  const { action } = el.dataset;
  if (action === 'month') {
    selectedMonth = el.dataset.month;
    rerender();
    return true;
  }
  if (action === 'category') {
    category = el.dataset.category;
    rerender();
    return true;
  }
  if (action !== 'pay' && action !== 'unpay') return false;
  const current = state.bills.find((b) => b.id === el.closest('[data-bill]').dataset.bill);
  if (current) {
    update('bill', current, { payment_state: action === 'pay' ? 'pagato' : 'da_pagare' })
      .then(() => toast(action === 'pay' ? `Segnato pagato: ${current.title}.` : `Di nuovo da pagare: ${current.title}.`))
      .catch((err) => toast(err.message));
  }
  return true;
}
