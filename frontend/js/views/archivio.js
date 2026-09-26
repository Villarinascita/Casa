import { html, toast } from '../dom.js';
import { formatDay } from '../dates.js';
import { state, update } from '../store.js';
import { empty, heading, sectionHead } from './common.js';

const STATE_LABELS = { da_pagare: 'Da pagare', addebito_previsto: 'Addebito previsto', pagato: 'Pagato' };
const NEXT_STATE = { da_pagare: 'addebito_previsto', addebito_previsto: 'pagato', pagato: 'da_pagare' };

function amountLabel(bill) {
  return bill.amount === null ? '—' : `${Number(bill.amount).toFixed(2)} €`;
}

function billRow(bill) {
  return html`<div class="item ${bill.payment_state === 'pagato' ? 'done' : ''}" data-bill="${bill.id}">
    <span class="time-pill">${amountLabel(bill)}</span>
    <button type="button" class="item-open" data-action="edit" data-kind="bill" data-id="${bill.id}">
      <span class="item-title">${bill.title}</span>
      <span class="meta">${[bill.supplier, bill.due_date ? `Scade ${formatDay(bill.due_date)}` : null].filter(Boolean).join(' · ')}</span>
    </button>
    <button type="button" data-action="cycle-state" aria-label="${bill.title}: ${STATE_LABELS[bill.payment_state]}, tocca per cambiare stato">${STATE_LABELS[bill.payment_state]} →</button>
  </div>`;
}

function totalDue() {
  return state.bills
    .filter((b) => b.payment_state !== 'pagato')
    .reduce((sum, b) => sum + (b.amount === null ? 0 : Number(b.amount)), 0);
}

export function render() {
  const categories = state.household?.bill_categories || [];
  const byCategory = categories.map((category) => ({
    category,
    bills: state.bills.filter((b) => b.category === category),
  })).filter((group) => group.bills.length);
  const others = state.bills.filter((b) => !categories.includes(b.category));
  if (others.length) byCategory.push({ category: 'Altro', bills: others });

  return html`
    ${heading('Le spese di casa', 'Costi da pagare.',
      'Bollette e costi trovati nelle email, più quelli che aggiungi tu con «+». Nessuno viene mai segnato pagato da solo.')}

    <section class="module">
      ${sectionHead(`Totale da pagare: ${totalDue().toFixed(2)} €`, html`<button type="button" class="primary" data-action="add" data-type="bill">＋ Nuovo costo</button>`)}
    </section>

    ${state.bills.length ? byCategory.map((group) => html`<section class="module">
      ${sectionHead(group.category)}
      ${group.bills.map(billRow)}
    </section>`) : html`<section class="module">${empty('Nessun costo registrato. Arriveranno dalle email, oppure aggiungine uno a mano.')}</section>`}
`;
}

/** Il pulsante di stato di una riga: gli altri tocchi (apri la scheda, +) li gestisce main.js. */
export function onAction(el) {
  if (el.dataset.action !== 'cycle-state') return false;
  const current = state.bills.find((b) => b.id === el.closest('[data-bill]').dataset.bill);
  if (current) update('bill', current, { payment_state: NEXT_STATE[current.payment_state] }).catch((err) => toast(err.message));
  return true;
}
