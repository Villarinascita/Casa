export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);

class SafeHtml {
  constructor(value) { this.value = value; }
  toString() { return this.value; }
}

/** Markup già sicuro, da non riscappare. */
export const raw = (value) => new SafeHtml(String(value));

function interpolate(value) {
  if (value instanceof SafeHtml) return value.value;
  if (Array.isArray(value)) return value.map(interpolate).join('');
  if (value === null || value === undefined || value === false) return '';
  return esc(value);
}

/** Template HTML che fa l'escape di ogni valore interpolato, salvo quelli marcati con raw() o prodotti da html``. */
export function html(strings, ...values) {
  return new SafeHtml(strings.reduce((out, part, i) => out + part + (i < values.length ? interpolate(values[i]) : ''), ''));
}

/** Identificativo casuale: crypto.randomUUID esiste solo in contesti sicuri (HTTPS o localhost). */
export function uid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export const announce = (text) => { $('#status').textContent = text; };

let toastTimer;
/** Messaggio temporaneo con azione facoltativa (es. «Annulla»). */
export function toast(message, action) {
  const box = $('#toast');
  clearTimeout(toastTimer);
  box.innerHTML = String(html`<span>${message}</span>${action ? html`<button type="button">${action.label}</button>` : ''}`);
  box.hidden = false;
  const button = $('button', box);
  if (button) {
    button.addEventListener('click', () => { hideToast(); action.run(); }, { once: true });
  }
  toastTimer = setTimeout(hideToast, action ? 8000 : 4000);
}

export function hideToast() {
  $('#toast').hidden = true;
}
