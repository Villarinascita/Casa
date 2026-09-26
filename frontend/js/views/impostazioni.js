import { $, $$, html, toast } from '../dom.js';
import { api } from '../api.js';
import { today } from '../dates.js';
import { create, find, importLegacy, logout, state, update, updateHousehold } from '../store.js';
import { heading, sectionHead } from './common.js';

const DEFAULT_AREAS = ['Bambina', 'Casa e bollette', 'Auto', 'Documenti'];
export const LEGACY_KEY = 'insieme-v1';
export const LEGACY_DONE_KEY = 'insieme-v1-importato';

function memberForm(member) {
  return html`<form class="member-row ${member.archived ? 'archived' : ''}" data-member="${member.id}">
    <label><span>Nome</span><input name="display_name" value="${member.display_name}" required maxlength="80"></label>
    <label><span>Legame</span><input name="relation" value="${member.relation || ''}" maxlength="80" placeholder="Es. nonna"></label>
    <div class="row-actions">
      <button type="submit">Salva</button>
      <button type="button" data-archive>${member.archived ? 'Ripristina' : 'Archivia'}</button>
    </div>
  </form>`;
}

export function render() {
  const areas = state.household?.areas || [];
  const allAreas = [...new Set([...DEFAULT_AREAS, ...areas])];
  const hasLegacy = Boolean(localStorage.getItem(LEGACY_KEY));
  return html`
    ${heading('A misura vostra', 'Impostazioni.', 'Familiari, aree e dati. Le modifiche valgono per tutta la famiglia.')}

    <section class="module">
      ${sectionHead('Familiari')}
      <p>Rinominare un familiare non tocca i suoi impegni. Chi non serve più si archivia: i suoi impegni passati restano leggibili.</p>
      ${state.members.map(memberForm)}
      <form id="add-member" class="member-row">
        <label><span>Nuovo familiare</span><input name="display_name" required maxlength="80" placeholder="Es. Nonna Lucia"></label>
        <label><span>Legame</span><input name="relation" maxlength="80" placeholder="Es. nonna"></label>
        <div class="row-actions"><button type="submit" class="primary">Aggiungi</button></div>
      </form>
    </section>

    ${state.me?.role === 'admin' ? html`<section class="module">
      ${sectionHead('Pagina dei nonni')}
      <p>I nonni entrano con il loro utente e vedono solo «Questa settimana»: gli appuntamenti e le attività assegnati a loro («Chi se ne occupa»). L'accesso resta ricordato sei mesi.</p>
      <form id="grandparent-members">
        <div class="checks">${state.members.filter((m) => !m.archived).map((m) => html`<label class="setting-check"><input type="checkbox" name="grandparent" value="${m.id}" ${(state.household?.grandparent_members || []).includes(m.id) ? 'checked' : ''}>${m.display_name}</label>`)}</div>
        <button type="submit" class="primary">Salva chi sono i nonni</button>
      </form>
      <h3>Accessi dei nonni</h3>
      <div id="grandparent-users" aria-live="polite">Caricamento…</div>
      <form id="grandparent-create" class="quick-add" autocomplete="off">
        <label class="grow"><span>Nuovo accesso (nome utente)</span><input name="login" required minlength="3" maxlength="40" placeholder="Es. nonna.anna"></label>
        <button type="submit" class="primary">Crea accesso</button>
      </form>
      <div id="grandparent-password" class="password-reveal" aria-live="polite" hidden></div>
    </section>` : ''}

    <section class="module">
      ${sectionHead('Aree della famiglia')}
      <form id="areas">
        <div class="checks">${allAreas.map((a) => html`<label class="setting-check"><input type="checkbox" name="area" value="${a}" ${areas.includes(a) ? 'checked' : ''}>${a}</label>`)}</div>
        <div class="quick-add">
          <label class="grow"><span>Aggiungi un'area</span><input name="custom" maxlength="60" placeholder="Es. Animali, Viaggi"></label>
          <button type="submit" class="primary">Salva le aree</button>
        </div>
      </form>
    </section>

    <section class="module">
      ${sectionHead('Categorie dei costi')}
      <p>Hermes smista così i costi trovati nelle email. Scrivi le sottocategorie separate da virgola; togli la spunta per eliminare una categoria. Se correggi la categoria di un costo, Hermes ricorda quel fornitore.</p>
      <form id="bill-categories">
        ${Object.entries(state.household?.bill_taxonomy || {}).map(([c, subs]) => html`<div class="taxonomy-row">
          <label class="setting-check"><input type="checkbox" name="category" value="${c}" checked>${c}</label>
          <label class="grow"><span class="visually-hidden">Sottocategorie di ${c}</span><input name="subs" data-category="${c}" value="${subs.join(', ')}" placeholder="Sottocategorie, separate da virgola"></label>
        </div>`)}
        <div class="quick-add">
          <label class="grow"><span>Nuova categoria</span><input name="custom" maxlength="60" placeholder="Es. Animali"></label>
          <label class="grow"><span>Sue sottocategorie</span><input name="custom_subs" placeholder="Es. Cibo, Veterinario"></label>
          <button type="submit" class="primary">Salva le categorie</button>
        </div>
      </form>
    </section>

    <section class="module">
      ${sectionHead('Email da ignorare')}
      <p>Le email da questi mittenti finiscono nel cestino di Gmail (recuperabili per 30 giorni) senza essere analizzate. Puoi indicare un dominio intero (newsletter.com) o un indirizzo preciso (promo@amazon.it) per tenere le email utili dello stesso mittente. Aggiungendone uno si spostano nel cestino anche quelle già in casella.</p>
      <form id="blocked-domains">
        <div class="checks">${(state.household?.blocked_email_domains || []).map((d) => html`<label class="setting-check"><input type="checkbox" name="domain" value="${d}" checked>${d}</label>`)}</div>
        <div class="quick-add">
          <label class="grow"><span>Aggiungi un dominio o un indirizzo</span><input name="custom" maxlength="320" placeholder="Es. newsletter.com o promo@amazon.it"></label>
          <button type="submit" class="primary">Salva</button>
        </div>
      </form>
      <div id="email-cleanups" aria-live="polite"></div>
      <h3>Pubblicità</h3>
      <p>Hermes riconosce le email pubblicitarie e le mette nel cestino da solo. Non tocca mai email con ordini, ricevute, bollette, appuntamenti o scadenze, né quelle speciali o importanti. Ogni settimana ricevi un riepilogo su Telegram.</p>
      <label class="setting-check"><input type="checkbox" id="auto-trash" ${state.household?.auto_trash_promotions === false ? '' : 'checked'}>Metti nel cestino la pubblicità da sola</label>
      <form id="kept-senders">
        <div class="checks">${(state.household?.kept_email_senders || []).map((d) => html`<label class="setting-check"><input type="checkbox" name="kept" value="${d}" checked>${d}</label>`)}</div>
        <div class="quick-add">
          <label class="grow"><span>Mittenti da tenere sempre</span><input name="custom" maxlength="320" placeholder="Es. conad.com"></label>
          <button type="submit" class="primary">Salva</button>
        </div>
      </form>
      <div id="auto-trashed" aria-live="polite"></div>
    </section>

    <section class="module">
      ${sectionHead('I vostri dati')}
      <p>Esporta una copia di tutto ciò che è salvato, oppure importa i dati della prima versione dell'app (file JSON esportato in precedenza).</p>
      <div class="button-row">
        <button type="button" id="export">Esporta JSON</button>
        <label class="file-button">Importa file della prima versione<input type="file" id="import-file" accept="application/json,.json"></label>
        ${hasLegacy ? html`<button type="button" id="import-device">Importa i dati salvati su questo dispositivo</button>` : ''}
      </div>
    </section>

    <section class="module">
      ${sectionHead('Telegram')}
      <p>Collega il tuo account per aggiungere attività, appuntamenti e spesa con messaggi scritti o vocali.</p>
      <p id="telegram-status">Verifica collegamento…</p>
      <div class="button-row">
        <button type="button" id="telegram-code">Crea codice di collegamento</button>
        <button type="button" id="telegram-disconnect" hidden>Scollega</button>
      </div>
      <p id="telegram-instructions" role="status"></p>
    </section>

    <section class="module">
      ${sectionHead('Google e Gmail')}
      <p>Collega il tuo account per importare gli appuntamenti dai calendari scelti. Le email che corrispondono al filtro diventano proposte da confermare.</p>
      <div id="google-settings" aria-live="polite">Caricamento collegamento Google…</div>
    </section>

    <section class="module">
      ${sectionHead('Proposte e conflitti')}
      <p>Le proposte trovate nelle email e i conflitti del calendario sono in <a href="#controllare">Da controllare</a>.</p>
    </section>

    <section class="module">
      ${sectionHead('Account')}
      <p>Hai effettuato l'accesso come <strong>${state.me?.login}</strong> nella famiglia <strong>${state.household?.name}</strong>.</p>
      <button type="button" id="logout">Esci</button>
    </section>`;
}

async function runImport(data) {
  if (!data || !Array.isArray(data.items) || !Array.isArray(data.members)) {
    throw new Error('Il file non sembra un\'esportazione della prima versione di Insieme.');
  }
  const result = await importLegacy({ members: data.members, items: data.items, areas: data.areas || [] });
  localStorage.setItem(LEGACY_DONE_KEY, new Date().toISOString());
  const skipped = result.skipped.length ? ` Non importati (senza data): ${result.skipped.join(', ')}.` : '';
  toast(`Importati ${result.events} appuntamenti, ${result.tasks} attività, ${result.shopping} prodotti.${skipped}`);
}

export function mount(root) {
  loadGoogle(root).catch((err) => { $('#google-settings', root).textContent = err.message; });
  loadCleanups(root).catch((err) => { $('#email-cleanups', root).textContent = err.message; });
  if ($('#grandparent-users', root)) mountGrandparents(root);
  loadAutoTrashed(root).catch((err) => { $('#auto-trashed', root).textContent = err.message; });
  api('GET', '/connections/telegram').then(({ connected }) => {
    $('#telegram-status', root).textContent = connected ? 'Account collegato.' : 'Account non ancora collegato.';
    $('#telegram-disconnect', root).hidden = !connected;
  }).catch((err) => { $('#telegram-status', root).textContent = err.message; });
  $('#telegram-code', root).addEventListener('click', async () => {
    try {
      const { code } = await api('POST', '/connections/telegram/start');
      $('#telegram-instructions', root).textContent = `Invia /link ${code} in chat privata al bot Telegram. Il codice scade tra 10 minuti.`;
    } catch (err) { toast(err.message); }
  });
  $('#telegram-disconnect', root).addEventListener('click', async () => {
    try {
      await api('DELETE', '/connections/telegram');
      $('#telegram-status', root).textContent = 'Account scollegato.';
      $('#telegram-disconnect', root).hidden = true;
      toast('Telegram scollegato.');
    } catch (err) { toast(err.message); }
  });
  $$('form[data-member]', root).forEach((form) => {
    const member = () => find('member', form.dataset.member);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await update('member', member(), {
          display_name: form.elements.display_name.value.trim(),
          relation: form.elements.relation.value.trim() || null,
        });
        toast('Familiare aggiornato.');
      } catch (err) { toast(err.message); }
    });
    $('[data-archive]', form).addEventListener('click', async () => {
      try {
        const current = member();
        await update('member', current, { archived: !current.archived });
        toast(current.archived ? 'Familiare ripristinato.' : 'Familiare archiviato.');
      } catch (err) { toast(err.message); }
    });
  });

  $('#add-member', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    try {
      await create('member', {
        display_name: form.elements.display_name.value.trim(),
        relation: form.elements.relation.value.trim() || null,
        sort_order: state.members.length,
      });
      toast('Familiare aggiunto.');
    } catch (err) { toast(err.message); }
  });

  $('#areas', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const areas = $$('[name=area]:checked', form).map((i) => i.value);
    const custom = form.elements.custom.value.trim();
    if (custom) areas.push(custom);
    try {
      await updateHousehold({ areas });
      toast('Aree salvate.');
    } catch (err) { toast(err.message); }
  });

  $('#bill-categories', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const split = (text) => text.split(',').map((s) => s.trim()).filter(Boolean);
    const kept = new Set($$('[name=category]:checked', form).map((i) => i.value));
    const bill_taxonomy = Object.fromEntries($$('[name=subs]', form)
      .filter((input) => kept.has(input.dataset.category))
      .map((input) => [input.dataset.category, split(input.value)]));
    const custom = form.elements.custom.value.trim();
    if (custom) bill_taxonomy[custom] = split(form.elements.custom_subs.value);
    try {
      await updateHousehold({ bill_taxonomy });
      toast('Categorie salvate.');
    } catch (err) { toast(err.message); }
  });

  $('#blocked-domains', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const blocked_email_domains = $$('[name=domain]:checked', form).map((i) => i.value);
    const custom = form.elements.custom.value.trim();
    if (custom) blocked_email_domains.push(custom);
    try {
      await updateHousehold({ blocked_email_domains });
      toast('Mittenti da ignorare salvati.');
    } catch (err) { toast(err.message); }
  });

  $('#auto-trash', root).addEventListener('change', async (e) => {
    try {
      await updateHousehold({ auto_trash_promotions: e.target.checked });
      toast(e.target.checked ? 'La pubblicità andrà nel cestino da sola.' : 'Pulizia automatica della pubblicità spenta.');
    } catch (err) { toast(err.message); }
  });

  $('#kept-senders', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const kept_email_senders = $$('[name=kept]:checked', form).map((i) => i.value);
    const custom = form.elements.custom.value.trim();
    if (custom) kept_email_senders.push(custom);
    try {
      await updateHousehold({ kept_email_senders });
      toast('Mittenti da tenere salvati.');
    } catch (err) { toast(err.message); }
  });

  $('#export', root).addEventListener('click', () => {
    const { household, members, events, tasks, shopping, bills } = state;
    const data = { exported_at: new Date().toISOString(), household, members, events, tasks, shopping, bills };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `insieme-${today()}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  $('#import-file', root).addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      await runImport(JSON.parse(await file.text()));
    } catch (err) {
      toast(err instanceof SyntaxError ? 'Il file non è un JSON valido.' : err.message);
    }
  });

  $('#import-device', root)?.addEventListener('click', async () => {
    try {
      await runImport(JSON.parse(localStorage.getItem(LEGACY_KEY)));
    } catch (err) { toast(err.message); }
  });

  $('#logout', root).addEventListener('click', logout);
}

const CLEANUP_LABELS = { running: 'in corso', done: 'completata' };

async function loadCleanups(root) {
  const box = $('#email-cleanups', root);
  if (!box) return;
  const cleanups = await api('GET', '/household/email-cleanups');
  box.innerHTML = cleanups.length ? String(html`<ul>${cleanups.map((c) => html`<li>${c.domain}: pulizia ${CLEANUP_LABELS[c.status] || c.status}, ${c.trashed_count} email nel cestino</li>`)}</ul>`) : '';
}

async function loadAutoTrashed(root) {
  const box = $('#auto-trashed', root);
  if (!box) return;
  const rows = await api('GET', '/household/auto-trashed');
  if (!rows.length) { box.innerHTML = ''; return; }
  const when = (iso) => new Date(iso).toLocaleDateString('it-IT', { day: 'numeric', month: 'short' });
  box.innerHTML = String(html`<p>Ultime email messe nel cestino da Hermes:</p><ul>${rows.map((r) => html`<li>${when(r.trashed_at)} · ${r.sender} · ${r.subject} ${r.sender.includes('@') ? html`<button type="button" data-keep="${r.sender.split('@').pop()}">Tieni questo mittente</button>` : ''}</li>`)}</ul>`);
  $$('[data-keep]', box).forEach((button) => button.addEventListener('click', async () => {
    const domain = button.dataset.keep;
    const kept = state.household?.kept_email_senders || [];
    const covered = (item) => item === domain || item.endsWith(`@${domain}`) || item.endsWith(`.${domain}`);
    try {
      await updateHousehold({
        kept_email_senders: [...new Set([...kept, domain])],
        blocked_email_domains: (state.household?.blocked_email_domains || []).filter((item) => !covered(item)),
      });
      toast(`Le email da ${domain} non andranno più nel cestino.`);
    } catch (err) { toast(err.message); }
  }));
}

async function loadGoogle(root) {
  const box = $('#google-settings', root);
  if (!box) return;
  const connection = await api('GET', '/connections/google');
  if (!connection.connected) {
    box.innerHTML = String(html`<p>Nessun account collegato.</p><button type="button" id="google-connect" class="primary">Collega Google</button>`);
    $('#google-connect', box).addEventListener('click', async () => {
      try {
        const { authorization_url: url } = await api('POST', '/connections/google/start');
        location.assign(url);
      } catch (err) { toast(err.message); }
    });
    return;
  }
  const available = await api('GET', '/connections/google/calendars/available');
  const selected = new Map(connection.calendars.map((calendar) => [calendar.id, calendar]));
  box.innerHTML = String(html`
    <p>Account collegato: <strong>${connection.email}</strong>.</p>
    ${connection.last_error ? html`<p role="alert">Ultima sincronizzazione: ${connection.last_error}</p>` : ''}
    <form id="gmail-filter"><label><span>Filtro Gmail</span><input name="query" value="${connection.gmail_query}" maxlength="500" required></label>
      <p>Usa la sintassi di ricerca Gmail, per esempio <code>label:Famiglia</code>.</p>
      <button type="submit">Salva filtro</button></form>
    <form id="google-calendars"><p>Scegli quali calendari leggere. “Solo occupato” nasconde titolo e note.</p>
      ${available.map((calendar) => html`<div class="member-row" data-calendar-id="${calendar.id}">
        <strong>${calendar.title}</strong>
        <label><span>Sincronizzazione</span><select name="mode">
          <option value="off" ${!selected.has(calendar.id) ? 'selected' : ''}>Escluso</option>
          <option value="full" ${selected.get(calendar.id)?.mode === 'full' ? 'selected' : ''}>Completa</option>
          <option value="busy" ${selected.get(calendar.id)?.mode === 'busy' ? 'selected' : ''}>Solo occupato</option>
        </select></label>
        <label><input type="radio" name="outbound" value="${calendar.id}" ${selected.get(calendar.id)?.outbound_default ? 'checked' : ''}
          ${['owner', 'writer'].includes(calendar.access_role) ? '' : 'disabled'}> Calendario per nuovi appuntamenti</label>
      </div>`)}
      <button type="submit">Salva calendari</button></form>
    <button type="button" id="google-reconnect">Ricollega Google (aggiorna i permessi)</button>
    <button type="button" id="google-disconnect">Scollega Google</button>`);
  $('#gmail-filter', box).addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      await api('PUT', '/connections/google/gmail', { body: { query: event.target.elements.query.value.trim() } });
      toast('Filtro Gmail salvato.');
    } catch (err) { toast(err.message); }
  });
  $('#google-calendars', box).addEventListener('submit', async (event) => {
    event.preventDefault();
    const defaultId = $('[name=outbound]:checked', event.target)?.value;
    const selections = $$('[data-calendar-id]', event.target).map((row) => ({
      id: row.dataset.calendarId,
      title: available.find((calendar) => calendar.id === row.dataset.calendarId)?.title || row.dataset.calendarId,
      mode: $('[name=mode]', row).value,
      outbound_default: row.dataset.calendarId === defaultId,
    })).filter((item) => item.mode !== 'off');
    try {
      await api('PUT', '/connections/google/calendars', { body: selections });
      toast('Calendari salvati.');
      await loadGoogle(root);
    } catch (err) { toast(err.message); }
  });
  $('#google-reconnect', box).addEventListener('click', async () => {
    try {
      const { authorization_url: url } = await api('POST', '/connections/google/start');
      location.assign(url);
    } catch (err) { toast(err.message); }
  });
  $('#google-disconnect', box).addEventListener('click', async () => {
    try {
      await api('DELETE', '/connections/google');
      toast('Google scollegato.');
      await loadGoogle(root);
    } catch (err) { toast(err.message); }
  });
}

/** La password si vede una volta sola: va scritta e data al nonno. */
function showPassword(root, { login, password }) {
  const box = $('#grandparent-password', root);
  box.hidden = false;
  box.innerHTML = String(html`<strong>Accesso per ${login}</strong>
    <span>Indirizzo: ${location.origin}</span><span>Utente: <b>${login}</b></span><span>Password: <b>${password}</b></span>
    <small>Scrivila adesso e dalla al nonno: poi non si vede più. Se si perde, crea una nuova password.</small>`);
}

async function loadGrandparents(root) {
  const box = $('#grandparent-users', root);
  const users = (await api('GET', '/household/users')).filter((u) => u.role === 'nonno');
  box.innerHTML = users.length ? String(html`<ul class="grandparent-list">${users.map((u) => html`<li>
    <span>${u.login}</span><button type="button" data-reset="${u.id}">Nuova password</button></li>`)}</ul>`)
    : '<p>Nessun accesso per i nonni.</p>';
  $$('[data-reset]', box).forEach((button) => button.addEventListener('click', async () => {
    try {
      showPassword(root, await api('POST', `/household/users/${button.dataset.reset}/password`));
      toast('Nuova password creata: il vecchio accesso del telefono è chiuso.');
    } catch (err) { toast(err.message); }
  }));
}

function mountGrandparents(root) {
  loadGrandparents(root).catch((err) => { $('#grandparent-users', root).textContent = err.message; });
  $('#grandparent-members', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await updateHousehold({ grandparent_members: $$('[name=grandparent]:checked', e.target).map((i) => i.value) });
      toast('Nonni salvati.');
    } catch (err) { toast(err.message); }
  });
  $('#grandparent-create', root).addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const created = await api('POST', '/household/users', { body: { login: e.target.elements.login.value } });
      e.target.reset();
      showPassword(root, created);
      await loadGrandparents(root);
    } catch (err) { toast(err.message); }
  });
}
