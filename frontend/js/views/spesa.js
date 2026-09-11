import { $, html, toast, uid } from '../dom.js';
import { clearCheckedShopping, create, state } from '../store.js';
import { empty, heading, sectionHead, shoppingRow } from './common.js';

let idempotencyKey = uid();

export function render() {
  const toBuy = state.shopping.filter((s) => !s.checked);
  const inCart = state.shopping.filter((s) => s.checked);
  return html`
    ${heading('Una cosa alla volta', 'La lista della spesa.', 'Condivisa tra tutti: spunta i prodotti quando sono nel carrello.')}
    <form id="quick-shopping" class="quick-add" autocomplete="off">
      <label class="grow"><span>Prodotto</span><input id="quick-label" name="label" required maxlength="120" placeholder="Es. latte, pile AA"></label>
      <label class="narrow"><span>Quantità</span><input name="quantity" maxlength="40" placeholder="Es. 2"></label>
      <button class="primary" type="submit">Aggiungi</button>
    </form>
    <p class="form-error" id="quick-error" role="alert"></p>
    ${sectionHead(`Da comprare (${toBuy.length})`)}
    ${toBuy.length ? toBuy.map(shoppingRow) : empty('La lista è vuota.')}
    ${inCart.length ? html`
      ${sectionHead(`Nel carrello (${inCart.length})`, html`<button type="button" data-action="clear-checked">Togli gli spuntati</button>`)}
      ${inCart.map(shoppingRow)}` : ''}`;
}

export function mount(root) {
  $('#quick-shopping', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const label = form.elements.label.value.trim();
    if (!label) return;
    try {
      await create('shopping', { label, quantity: form.elements.quantity.value.trim() || null }, idempotencyKey);
      idempotencyKey = uid();
      $('#quick-label')?.focus();
    } catch (err) {
      $('#quick-error').textContent = err.message;
    }
  });
}

export function onAction(el) {
  if (el.dataset.action !== 'clear-checked') return false;
  clearCheckedShopping()
    .then((undo) => toast('Prodotti spuntati tolti dalla lista.', { label: 'Annulla', run: () => undo().catch((err) => toast(err.message)) }))
    .catch((err) => toast(err.message));
  return true;
}
