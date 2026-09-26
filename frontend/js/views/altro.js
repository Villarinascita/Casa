import { $, html, toast } from '../dom.js';
import { api } from '../api.js';
import { logout, state } from '../store.js';
import { heading, sectionHead } from './common.js';

const link = (href, title, text) =>
  html`<a class="more-link" href="${href}"><strong>${title}</strong><span>${text}</span></a>`;

export function render() {
  return html`
    ${heading('Tutto il resto', 'Altro.', '')}
    <div class="more-links">
      ${link('#famiglia', 'Famiglia', 'Chi fa cosa: impegni e attività di ciascuno.')}
      ${link('#impostazioni', 'Impostazioni', 'Familiari, categorie, email da ignorare, Telegram e Google.')}
    </div>
    <section class="panel password-box">
      ${sectionHead('Cambia password')}
      <form id="password-form" autocomplete="on">
        <input type="text" name="username" value="${state.me?.login || ''}" autocomplete="username" hidden>
        <label><span>Password attuale</span><input type="password" name="current" required autocomplete="current-password"></label>
        <label><span>Nuova password (almeno 10 caratteri)</span><input type="password" name="new" required minlength="10" autocomplete="new-password"></label>
        <label><span>Ripeti la nuova password</span><input type="password" name="repeat" required minlength="10" autocomplete="new-password"></label>
        <p class="form-error" id="password-error" role="alert"></p>
        <button type="submit" class="primary">Salva la nuova password</button>
      </form>
    </section>
    <p class="intro">Accesso come <strong>${state.me?.login}</strong> nella famiglia <strong>${state.household?.name}</strong>.</p>
    <button type="button" id="logout-more">Esci</button>`;
}

export function mount(root) {
  $('#logout-more', root).addEventListener('click', logout);
  $('#password-form', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = e.target.elements;
    const error = $('#password-error', root);
    if (f.new.value !== f.repeat.value) {
      error.textContent = 'Le due nuove password non coincidono.';
      return;
    }
    try {
      await api('POST', '/auth/password', { body: { current: f.current.value, new: f.new.value } });
      e.target.reset();
      error.textContent = '';
      toast('Password cambiata. Usala dal prossimo accesso.');
    } catch (err) { error.textContent = err.message; }
  });
}
