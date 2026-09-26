import { $, html } from '../dom.js';
import { logout, state } from '../store.js';
import { heading } from './common.js';

const link = (href, title, text) =>
  html`<a class="more-link" href="${href}"><strong>${title}</strong><span>${text}</span></a>`;

export function render() {
  return html`
    ${heading('Tutto il resto', 'Altro.', '')}
    <div class="more-links">
      ${link('#famiglia', 'Famiglia', 'Chi fa cosa: impegni e attività di ciascuno.')}
      ${link('#impostazioni', 'Impostazioni', 'Familiari, categorie, email da ignorare, Telegram e Google.')}
    </div>
    <p class="intro">Accesso come <strong>${state.me?.login}</strong> nella famiglia <strong>${state.household?.name}</strong>.</p>
    <button type="button" id="logout-more">Esci</button>`;
}

export function mount(root) {
  $('#logout-more', root).addEventListener('click', logout);
}
