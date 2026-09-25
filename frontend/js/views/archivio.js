import { html, toast } from '../dom.js';
import { formatDay } from '../dates.js';
import { create, remove, state, update } from '../store.js';
import { empty, heading, sectionHead } from './common.js';

const STATE_LABELS = { da_pagare: 'Da pagare', addebito_previsto: 'Addebito previsto', pagato: 'Pagato' };
const NEXT_STATE = { da_pagare: 'addebito_previsto', addebito_previsto: 'pagato', pagato: 'da_pagare' };

function amountLabel(bill) {
  return bill.amount === null ? '—' : `${Number(bill.amount).toFixed(2)} €`;
}

function billRow(bill) {
  return html`<div class="item ${bill.payment_state === 'pagato' ? 'done' : ''}" data-bill="${bill.id}">
    <span class="time-pill">${amountLabel(bill)}</span>
    <span class="item-title">${bill.title}</span>
    <span class="meta">${[bill.supplier, bill.due_date ? `Scade ${formatDay(bill.due_date)}` : null,
      STATE_LABELS[bill.payment_state]].filter(Boolean).join(' · ')}</span>
    <button type="button" data-action="cycle-state" aria-label="Cambia stato">${STATE_LABELS[bill.payment_state]} →</button>
    <button type="button" class="delete" data-action="delete-bill" aria-label="Elimina ${bill.title}">Elimina</button>
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
    ${heading('Le informazioni di casa', 'Costi da pagare.',
      'Bollette e costi trovati nelle email, più quelli che aggiungi tu. Nessuno viene mai segnato pagato da solo.')}

    <section class="module">
      <p class="intro">Totale da pagare: <strong>${totalDue().toFixed(2)} €</strong></p>
    </section>

    ${state.bills.length ? byCategory.map((group) => html`<section class="module">
      ${sectionHead(group.category)}
      ${group.bills.map(billRow)}
    </section>`) : html`<section class="module">${empty('Nessun costo registrato. Arriveranno dalle email, oppure aggiungine uno a mano.')}</section>`}

    <section class="module">
      ${sectionHead('Aggiungi un costo a mano')}
      <form id="add-bill">
        <label><span>Categoria</span>
          <select name="category">${categories.map((c) => html`<option value="${c}">${c}</option>`)}</select>
        </label>
        <label><span>Titolo</span><input name="title" required maxlength="180" placeholder="Es. Bolletta gas"></label>
        <label><span>Fornitore</span><input name="supplier" maxlength="180" placeholder="Facoltativo"></label>
        <label><span>Importo (€)</span><input name="amount" type="number" step="0.01" min="0" placeholder="Facoltativo"></label>
        <label><span>Scadenza</span><input name="due_date" type="date"></label>
        <button type="submit" class="primary">Aggiungi</button>
      </form>
    </section>`;
}

export function mount(root) {
  const form = root.querySelector('#add-bill');
  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const el = event.target.elements;
    try {
      await create('bill', {
        category: el.category.value,
        title: el.title.value.trim(),
        supplier: el.supplier.value.trim() || null,
        amount: el.amount.value === '' ? null : el.amount.value,
        due_date: el.due_date.value || null,
      });
      form.reset();
    } catch (err) { toast(err.message); }
  });

  root.querySelectorAll('[data-bill]').forEach((row) => {
    const bill = () => state.bills.find((b) => b.id === row.dataset.bill);
    row.querySelector('[data-action="cycle-state"]')?.addEventListener('click', async () => {
      const current = bill();
      try {
        await update('bill', current, { payment_state: NEXT_STATE[current.payment_state] });
      } catch (err) { toast(err.message); }
    });
    row.querySelector('[data-action="delete-bill"]')?.addEventListener('click', async () => {
      const current = bill();
      try {
        const undo = await remove('bill', current);
        toast(`Eliminato: ${current.title}.`, { label: 'Annulla', run: () => undo().catch((e) => toast(e.message)) });
      } catch (err) { toast(err.message); }
    });
  });
}
