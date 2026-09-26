import { $, announce, html, toast } from './dom.js';
import { formatLongToday, msUntilMidnight } from './dates.js';
import { openEditor, setupEditor } from './editor.js';
import { find, loadSession, refresh, reviewCount, setOnline, state, subscribe, update } from './store.js';
import * as altro from './views/altro.js';
import * as archivio from './views/archivio.js';
import * as attivita from './views/attivita.js';
import * as calendario from './views/calendario.js';
import * as controllare from './views/controllare.js';
import * as famiglia from './views/famiglia.js';
import * as impostazioni from './views/impostazioni.js';
import * as loginView from './views/login.js';
import * as oggi from './views/oggi.js';
import * as spesa from './views/spesa.js';

const ROUTES = {
  oggi: { label: 'Oggi', view: oggi },
  calendario: { label: 'Calendario', view: calendario },
  attivita: { label: 'Attività', view: attivita },
  spesa: { label: 'Spesa', view: spesa },
  famiglia: { label: 'Famiglia', view: famiglia },
  archivio: { label: 'Casa e documenti', view: archivio },
  impostazioni: { label: 'Impostazioni', view: impostazioni },
  controllare: { label: 'Da controllare', view: controllare },
  altro: { label: 'Altro', view: altro },
};
/** Le cinque voci del menu; le altre rotte accendono la voce da cui si raggiungono. */
const NAV = [['oggi', 'Oggi'], ['calendario', 'Calendario'], ['attivita', 'Da fare'], ['archivio', 'Costi'], ['altro', 'Altro']];
const NAV_OF = { spesa: 'attivita', famiglia: 'altro', impostazioni: 'altro', controllare: 'oggi' };
const SYNC_INTERVAL_MS = 30_000;

let startupError = null;
let pendingRender = false;

const currentRoute = () => (ROUTES[location.hash.slice(1)] ? location.hash.slice(1) : 'oggi');

function isTyping() {
  const el = document.activeElement;
  return $('#screen').contains(el) && el.matches('input, textarea, select');
}

/** Chiave per ritrovare il pulsante che aveva il focus dopo aver ridisegnato la schermata. */
function focusKey() {
  const el = document.activeElement;
  if (!el?.dataset?.action || !$('#screen').contains(el)) return null;
  const { action, id, day, step } = el.dataset;
  const [name, value] = id ? ['id', id] : day ? ['day', day] : step ? ['step', step] : [];
  return `[data-action="${action}"]${name ? `[data-${name}="${CSS.escape(value)}"]` : ''}`;
}

function renderChrome() {
  $('#date').textContent = formatLongToday();
  const loggedIn = Boolean(state.me);
  document.body.classList.toggle('logged-out', !loggedIn);
  const active = NAV_OF[currentRoute()] || currentRoute();
  const pending = reviewCount();
  const link = ([id, label]) => html`<a href="#${id}" class="${active === id ? 'active' : ''}" ${active === id ? html`aria-current="page"` : ''}>${label}${id === 'oggi' && pending ? html`<span class="nav-badge" aria-label="${pending} da controllare">${pending}</span>` : ''}</a>`;
  $('#nav').innerHTML = loggedIn ? String(html`${NAV.map(link)}`) : '';
  // Telefono: barra in basso con «+» al centro; «Altro» è in alto a destra.
  $('#tabbar').innerHTML = loggedIn
    ? String(html`${NAV.slice(0, 2).map(link)}<button type="button" class="tab-add" data-add aria-label="Aggiungi">＋</button>${NAV.slice(2, 4).map(link)}`)
    : '';
  const sync = $('#sync');
  if (!state.online) sync.textContent = 'Offline · le modifiche non si possono salvare';
  else if (state.lastSync) sync.textContent = `Aggiornato alle ${state.lastSync.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })}`;
  else sync.textContent = '';
  sync.classList.toggle('offline', !state.online);
  renderLegacyBanner();
}

function renderLegacyBanner() {
  const banner = $('#legacy-banner');
  const show = Boolean(state.me) && localStorage.getItem(impostazioni.LEGACY_KEY) && !localStorage.getItem(impostazioni.LEGACY_DONE_KEY);
  banner.hidden = !show;
}

export function render({ background = false } = {}) {
  if (background && isTyping()) {
    // Non cancellare ciò che l'utente sta scrivendo: si aggiorna appena lascia il campo.
    pendingRender = true;
    renderChrome();
    return;
  }
  pendingRender = false;
  renderChrome();
  const screen = $('#screen');
  if (startupError) {
    screen.innerHTML = String(html`<div class="login"><h1>Server non raggiungibile.</h1><p class="intro">${startupError}</p><button type="button" class="primary" id="retry">Riprova</button></div>`);
    $('#retry').addEventListener('click', start);
    return;
  }
  const view = state.me ? ROUTES[currentRoute()].view : loginView;
  const key = focusKey();
  screen.innerHTML = String(view.render());
  view.mount?.(screen);
  if (key) $(key, screen)?.focus();
}

async function handleAction(el) {
  const view = ROUTES[currentRoute()].view;
  if (view.onAction?.(el, render)) return;
  const { action, kind, id } = el.dataset;
  if (action === 'add') return openEditor({ type: el.dataset.type, date: el.dataset.date });
  if (action === 'edit') return openEditor({ type: kind, entity: find(kind, id) });
  if (!state.online) return toast('Sei offline: riprova quando torna la connessione.');
  const item = find(kind, id);
  if (!item) return;
  if (action === 'toggle' && kind === 'task') {
    await update('task', item, { status: item.status === 'done' ? 'open' : 'done' });
  } else if (action === 'toggle' && kind === 'shopping') {
    await update('shopping', item, { checked: !item.checked });
  }
}

function defaultTypeForRoute() {
  return { spesa: 'shopping', attivita: 'task', archivio: 'bill' }[currentRoute()] || 'event';
}

async function sync() {
  if (!state.me || !state.online || document.visibilityState !== 'visible') return;
  try {
    await refresh();
  } catch {
    // Errore temporaneo: il prossimo ciclo riprova. Un 401 porta già alla schermata di accesso.
  }
}

function scheduleMidnight() {
  setTimeout(() => { render({ background: true }); scheduleMidnight(); }, msUntilMidnight() + 1000);
}

async function start() {
  startupError = null;
  try {
    if (await loadSession()) await refresh();
  } catch (err) {
    startupError = err.message;
  }
  render();
}

function setup() {
  setupEditor();
  subscribe((reason) => render({ background: reason === 'refresh' }));
  window.addEventListener('hashchange', () => { render(); $('#screen h1')?.focus(); });
  $('#screen').addEventListener('click', (e) => {
    const el = e.target.closest('[data-action]');
    if (el) handleAction(el).catch((err) => toast(err.message));
  });
  $('#screen').addEventListener('focusout', () => {
    setTimeout(() => { if (pendingRender && !isTyping()) render(); }, 0);
  });
  $('#add').addEventListener('click', () => openEditor({ type: defaultTypeForRoute() }));
  $('#tabbar').addEventListener('click', (e) => {
    if (e.target.closest('[data-add]')) openEditor({ type: defaultTypeForRoute() });
  });
  $('#legacy-import').addEventListener('click', () => { location.hash = '#impostazioni'; });
  $('#legacy-dismiss').addEventListener('click', () => {
    localStorage.setItem(impostazioni.LEGACY_DONE_KEY, 'ignorato');
    renderLegacyBanner();
  });
  window.addEventListener('online', () => { setOnline(true); sync(); });
  window.addEventListener('offline', () => setOnline(false));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      render({ background: true });
      sync();
    }
  });
  setInterval(sync, SYNC_INTERVAL_MS);
  scheduleMidnight();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => announce('Modalità offline non disponibile in questo browser.'));
  }
}

setup();
start();
