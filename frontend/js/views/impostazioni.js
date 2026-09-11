import { $, $$, html, toast } from '../dom.js';
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
      ${sectionHead('I vostri dati')}
      <p>Esporta una copia di tutto ciò che è salvato, oppure importa i dati della prima versione dell'app (file JSON esportato in precedenza).</p>
      <div class="button-row">
        <button type="button" id="export">Esporta JSON</button>
        <label class="file-button">Importa file della prima versione<input type="file" id="import-file" accept="application/json,.json"></label>
        ${hasLegacy ? html`<button type="button" id="import-device">Importa i dati salvati su questo dispositivo</button>` : ''}
      </div>
    </section>

    <section class="module">
      ${sectionHead('Collegamenti previsti')}
      <p>Assistente vocale · Gmail · Calendario lavorativo · WhatsApp</p>
      <span class="chip">Non ancora collegati</span>
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

  $('#export', root).addEventListener('click', () => {
    const { household, members, events, tasks, shopping } = state;
    const data = { exported_at: new Date().toISOString(), household, members, events, tasks, shopping };
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
