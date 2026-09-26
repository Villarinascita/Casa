// «Da controllare»: proposte dalle email e conflitti del calendario in un unico posto.

import { $, $$, html, toast } from '../dom.js';
import { api } from '../api.js';
import { formatDay } from '../dates.js';
import { refresh, state } from '../store.js';
import { heading } from './common.js';

const FILTERS = [['tutto', 'Tutto'], ['email', 'Email'], ['calendario', 'Calendario']];
let filter = 'tutto';
let confirmingStale = false;
let data = { proposals: [], conflicts: [], loaded: false, error: null };

const senderName = (sender) => (sender || '').replace(/<.*>/, '').replace(/"/g, '').trim() || 'mittente sconosciuto';

function proposalTitle(item) {
  const d = item.data || {};
  if (item.kind === 'shopping') return `Aggiungere «${d.label}» alla spesa?`;
  if (item.kind === 'event') return `Nuovo appuntamento: ${d.title}`;
  return `Nuova attività: ${d.title}`;
}

function proposalDetail(item) {
  const d = item.data || {};
  if (item.kind === 'event' && d.start_at) return new Date(d.start_at).toLocaleString('it-IT', { dateStyle: 'full', timeStyle: 'short' });
  if (item.kind === 'event' && d.start_date) return `${formatDay(d.start_date, { weekday: 'long', day: 'numeric', month: 'long' })}, tutto il giorno`;
  if (item.kind === 'task' && d.due_date) return `Entro ${formatDay(d.due_date, { weekday: 'long', day: 'numeric', month: 'long' })}`;
  return item.subject ? `«${item.subject}»` : '';
}

const KIND_LABEL = { shopping: 'SPESA', event: 'APPUNTAMENTO', task: 'ATTIVITÀ' };

const proposalCard = (item) => html`<article class="review-card" data-proposal="${item.id}">
  <span class="review-kind ${item.kind}">${KIND_LABEL[item.kind] || 'PROPOSTA'} · dall'email di ${senderName(item.sender)}</span>
  <strong class="review-title">${proposalTitle(item)}</strong>
  <span class="meta">${proposalDetail(item)}</span>
  <div class="review-actions">
    <button type="button" class="primary" data-decision="accept">Aggiungi</button>
    <button type="button" data-decision="reject">Ignora</button>
  </div>
</article>`;

const conflictCard = (item) => html`<article class="review-card" data-conflict="${item.id}">
  <span class="review-kind event">CALENDARIO · ${item.calendar}</span>
  <strong class="review-title">${item.remote.deleted ? `«${item.local_title}» è stato eliminato su Google` : `«${item.local_title}» è diverso su Google`}</strong>
  <span class="meta">In Insieme: ${item.local_title}${item.remote.deleted ? '' : ` · Su Google: ${item.remote.title}`}</span>
  <div class="review-actions">
    <button type="button" class="primary" data-choice="google">${item.remote.deleted ? 'Eliminalo anche qui' : 'Tieni Google'}</button>
    ${item.remote.deleted ? '' : html`<button type="button" data-choice="local">Tieni Insieme</button>`}
  </div>
</article>`;

function staleCard() {
  const stale = state.review.stale;
  if (!stale || filter === 'calendario') return '';
  return html`<div class="review-card stale">
    <strong>Arretrati</strong>
    <span class="meta">${stale === 1 ? '1 proposta aspetta' : `${stale} proposte aspettano`} da più di 30 giorni: probabilmente non servono più.</span>
    <div class="review-actions">${confirmingStale
      ? html`<button type="button" class="primary" data-stale="confirm">Sì, ignora ${stale === 1 ? 'la proposta' : `tutte le ${stale}`}</button><button type="button" data-stale="cancel">No</button>`
      : html`<button type="button" data-stale="ask">Ignora le più vecchie di 30 giorni</button>`}</div>
  </div>`;
}

export function render() {
  const counts = { tutto: data.proposals.length + data.conflicts.length, email: data.proposals.length, calendario: data.conflicts.length };
  const proposals = filter === 'calendario' ? [] : data.proposals;
  const conflicts = filter === 'email' ? [] : data.conflicts;
  let body;
  if (data.error) body = html`<p class="empty">${data.error}</p>`;
  else if (!data.loaded) body = html`<p class="empty">Caricamento…</p>`;
  else if (!proposals.length && !conflicts.length) body = html`<p class="empty">Niente da controllare. Quando Hermes trova qualcosa nelle email lo vedi qui.</p>`;
  else body = html`${staleCard()}${conflicts.map(conflictCard)}${proposals.map(proposalCard)}`;
  return html`
    ${heading('Hermes chiede a te', 'Da controllare.', 'Cose trovate nelle email e nel calendario che aspettano una tua decisione. Un tocco per scegliere.')}
    <div class="filter-pills" role="group" aria-label="Filtra">
      ${FILTERS.map(([id, label]) => html`<button type="button" data-filter="${id}" aria-pressed="${filter === id}">${label} ${counts[id]}</button>`)}
    </div>
    <div class="review-list">${body}</div>`;
}

async function load(rerender) {
  try {
    const [proposals, conflicts] = await Promise.all([
      api('GET', '/proposals?status=pending'),
      api('GET', '/calendar/conflicts').catch(() => []),
    ]);
    data = { proposals, conflicts, loaded: true, error: null };
  } catch (err) {
    data = { ...data, loaded: true, error: err.message };
  }
  rerender();
}

/** Dopo una decisione: ricarica la lista e i conteggi del menu. */
async function after(rerender, message) {
  toast(message);
  await refresh().catch(() => {});
  await load(rerender);
}

export function mount(root) {
  const rerender = () => {
    if (!root.isConnected || location.hash !== '#controllare') return;
    root.innerHTML = String(render());
    bind(root, rerender);
  };
  bind(root, rerender);
  load(rerender); // sempre aggiornato quando si apre la pagina
}

function bind(root, rerender) {
  $$('[data-filter]', root).forEach((button) => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    rerender();
  }));
  $$('[data-decision]', root).forEach((button) => button.addEventListener('click', async () => {
    const item = data.proposals.find((p) => p.id === button.closest('[data-proposal]').dataset.proposal);
    button.disabled = true;
    try {
      await api('POST', `/proposals/${item.id}/review`, { body: { decision: button.dataset.decision }, version: item.version });
      await after(rerender, button.dataset.decision === 'accept' ? 'Aggiunto.' : 'Ignorato.');
    } catch (err) { toast(err.message); button.disabled = false; }
  }));
  $$('[data-choice]', root).forEach((button) => button.addEventListener('click', async () => {
    const id = button.closest('[data-conflict]').dataset.conflict;
    button.disabled = true;
    try {
      await api('POST', `/calendar/conflicts/${id}/resolve`, { body: { choice: button.dataset.choice } });
      await after(rerender, 'Conflitto risolto.');
    } catch (err) { toast(err.message); button.disabled = false; }
  }));
  $('.review-card.stale', root)?.addEventListener('click', async (e) => {
    const action = e.target.closest('[data-stale]')?.dataset.stale;
    if (action === 'ask' || action === 'cancel') {
      confirmingStale = action === 'ask';
      rerender();
      return;
    }
    if (action !== 'confirm') return;
    try {
      const { rejected } = await api('POST', '/proposals/reject-stale', { body: { days: 30 } });
      confirmingStale = false;
      await after(rerender, `${rejected} ${rejected === 1 ? 'proposta ignorata' : 'proposte ignorate'}.`);
    } catch (err) { toast(err.message); }
  });
}
