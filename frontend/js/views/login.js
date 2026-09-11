import { $, html } from '../dom.js';
import { login } from '../store.js';

export function render() {
  return html`<div class="login">
    <div class="brand-large">insieme</div>
    <p class="intro">Accedi per vedere e aggiornare gli impegni della famiglia.</p>
    <form id="login-form" autocomplete="on">
      <label><span>Nome utente</span><input name="login" autocomplete="username" required autocapitalize="none" spellcheck="false"></label>
      <label><span>Password</span><input name="password" type="password" autocomplete="current-password" required></label>
      <button class="primary" type="submit">Entra</button>
      <p class="form-error" id="login-error" role="alert"></p>
    </form>
    <p class="hint">Gli account si creano dal computer che ospita Insieme (vedi README).</p>
  </div>`;
}

export function mount(root) {
  const form = $('#login-form', root);
  form.elements.login.focus();
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const button = $('[type=submit]', form);
    button.disabled = true;
    $('#login-error').textContent = '';
    try {
      await login(form.elements.login.value.trim(), form.elements.password.value);
    } catch (err) {
      $('#login-error').textContent = err.message;
      form.elements.password.value = '';
      form.elements.password.focus();
    } finally {
      button.disabled = false;
    }
  });
}
