// Finestra di inserimento e modifica: campi diversi per appuntamento, attività, spesa e costo.

import { $, $$, html, toast, uid } from './dom.js';
import { dayOfInstant, timeOf, toInstant, today } from './dates.js';
import { activeMembers, create, memberById, remove, state, update } from './store.js';

const TITLES = {
  event: ['Nuovo appuntamento', 'Modifica appuntamento'],
  task: ['Nuova attività', 'Modifica attività'],
  shopping: ['Aggiungi alla spesa', 'Modifica voce della spesa'],
  bill: ['Nuovo costo', 'Modifica costo'],
};
const label = (entity) => entity.title || entity.label;

let editing = null; // entità in modifica, null se nuova
let idempotencyKey = null;
let opener = null;

const dialog = () => $('#editor');
const form = () => $('#entry');

function currentType() {
  return form().elements.type.value;
}

function syncFields() {
  const type = currentType();
  const f = form();
  $$('[data-for]', f).forEach((el) => { el.hidden = !el.dataset.for.split(' ').includes(type); });
  const allDay = f.elements.all_day.checked;
  $$('[data-timed]', f).forEach((el) => { el.hidden = type !== 'event' || allDay; });
  $('#editor-title').textContent = TITLES[type][editing ? 1 : 0];
  f.elements.title.placeholder = {
    event: 'Es. Nuoto, visita dal pediatra',
    task: 'Es. Chiamare il tecnico, rinnovare il bollo',
    shopping: 'Es. Latte, pile AA',
    bill: 'Es. Bolletta gas, rata auto',
  }[type];
  $('#title-label').textContent = { shopping: 'Prodotto', bill: 'Titolo' }[type] || 'Cosa?';
  $('#editor-delete').hidden = !editing;
}

function fillMembers(selectedId) {
  const members = activeMembers();
  const selected = selectedId && memberById(selectedId);
  if (selected?.archived) members.push(selected);
  form().elements.member_id.innerHTML = String(html`<option value="">Da assegnare</option>${members.map(
    (m) => html`<option value="${m.id}" ${m.id === selectedId ? 'selected' : ''}>${m.display_name}${m.archived ? ' (archiviato)' : ''}</option>`,
  )}`);
}

const taxonomy = () => state.household?.bill_taxonomy || { Altro: [] };

function fillCategories(selected, selectedSub) {
  const categories = Object.keys(taxonomy());
  if (selected && !categories.includes(selected)) categories.push(selected);
  form().elements.category.innerHTML = String(html`${categories.map(
    (c) => html`<option value="${c}" ${c === selected ? 'selected' : ''}>${c}</option>`,
  )}`);
  fillSubcategories(selectedSub);
}

/** Sottocategorie della categoria scelta; quella del costo resta anche se proposta da Hermes. */
function fillSubcategories(selected) {
  const subs = [...(taxonomy()[form().elements.category.value] || [])];
  if (selected && !subs.includes(selected)) subs.push(selected);
  form().elements.subcategory.innerHTML = String(html`<option value="">Nessuna</option>${subs.map(
    (s) => html`<option value="${s}" ${s === selected ? 'selected' : ''}>${s}</option>`,
  )}`);
}

export function openEditor({ type = 'event', date, entity = null } = {}) {
  const f = form();
  editing = entity;
  idempotencyKey = uid();
  opener = document.activeElement;
  f.reset();
  $('#form-error').textContent = '';
  f.elements.type.value = type;
  $$('[name=type]', f).forEach((radio) => { radio.disabled = Boolean(entity); });
  fillMembers(entity?.member_id);
  fillCategories(entity?.category, entity?.subcategory);

  if (entity && type === 'event') {
    f.elements.title.value = entity.title;
    f.elements.all_day.checked = entity.all_day;
    f.elements.date.value = entity.all_day ? entity.start_date : dayOfInstant(entity.start_at);
    if (!entity.all_day) {
      f.elements.start.value = timeOf(entity.start_at);
      f.elements.end.value = entity.end_at ? timeOf(entity.end_at) : '';
    }
    f.elements.location.value = entity.location || '';
    f.elements.notes.value = entity.notes || '';
  } else if (entity && type === 'task') {
    f.elements.title.value = entity.title;
    f.elements.due_date.value = entity.due_date || '';
    f.elements.notes.value = entity.notes || '';
    f.elements.remind_at.value = entity.remind_at ? `${dayOfInstant(entity.remind_at)}T${timeOf(entity.remind_at)}` : '';
    f.elements.repeat.value = entity.repeat || '';
  } else if (entity && type === 'shopping') {
    f.elements.title.value = entity.label;
    f.elements.quantity.value = entity.quantity || '';
  } else if (entity && type === 'bill') {
    f.elements.title.value = entity.title;
    f.elements.supplier.value = entity.supplier || '';
    f.elements.amount.value = entity.amount ?? '';
    f.elements.bill_due.value = entity.due_date || '';
  } else {
    f.elements.date.value = date || today();
    if (type === 'task' && date) f.elements.due_date.value = date;
  }
  syncFields();
  dialog().showModal();
  f.elements.title.focus();
}

function closeEditor() {
  dialog().close();
}

function payload() {
  const f = form().elements;
  const type = currentType();
  const title = f.title.value.trim();
  if (!title) return { error: 'Scrivi cosa vuoi ricordare.' };
  if (type === 'shopping') return { data: { label: title, quantity: f.quantity.value.trim() || null } };
  if (type === 'bill') {
    return { data: { title, category: f.category.value, supplier: f.supplier.value.trim() || null,
      amount: f.amount.value === '' ? null : f.amount.value, due_date: f.bill_due.value || null,
      subcategory: f.subcategory.value || null } };
  }

  const common = { title, member_id: f.member_id.value || null, notes: f.notes.value.trim() || null };
  if (type === 'task') {
    if (f.repeat.value && !f.remind_at.value) return { error: 'Indica quando inviare il promemoria ricorrente.' };
    const [remindDate, remindTime] = f.remind_at.value.split('T');
    return { data: { ...common, due_date: f.due_date.value || null,
      remind_at: remindDate ? toInstant(remindDate, remindTime) : null,
      repeat: f.repeat.value || null } };
  }

  const date = f.date.value;
  if (!date) return { error: 'Indica la data dell’appuntamento.' };
  const event = { ...common, location: f.location.value.trim() || null };
  if (f.all_day.checked) return { data: { ...event, all_day: true, start_date: date } };
  if (!f.start.value) return { error: 'Indica l’ora di inizio, oppure scegli «Tutto il giorno».' };
  if (f.end.value && f.end.value < f.start.value) return { error: 'L’ora di fine precede quella di inizio.' };
  return {
    data: {
      ...event,
      all_day: false,
      start_at: toInstant(date, f.start.value),
      end_at: f.end.value ? toInstant(date, f.end.value) : null,
    },
  };
}

async function submit(e) {
  e.preventDefault();
  const { data, error } = payload();
  const errorBox = $('#form-error');
  if (error) {
    errorBox.textContent = error;
    return;
  }
  if (!state.online) {
    errorBox.textContent = 'Sei offline: le modifiche si potranno salvare quando torna la connessione.';
    return;
  }
  const button = $('[type=submit]', form());
  button.disabled = true;
  const wasEditing = Boolean(editing);
  try {
    const type = currentType();
    if (editing) await update(type, editing, data);
    else await create(type, data, idempotencyKey);
    closeEditor();
    toast(wasEditing ? 'Modifiche salvate.' : 'Salvato. Lo vedono tutti i familiari collegati.');
  } catch (err) {
    errorBox.textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

/** «Elimina» sta nella scheda, non sulle righe: chiude, elimina e offre «Annulla». */
async function deleteEditing() {
  const entity = editing;
  const type = currentType();
  if (!entity) return;
  if (!state.online) {
    $('#form-error').textContent = 'Sei offline: riprova quando torna la connessione.';
    return;
  }
  closeEditor();
  try {
    const undo = await remove(type, entity);
    toast(`Eliminato: ${label(entity)}.`, { label: 'Annulla', run: () => undo().catch((err) => toast(err.message)) });
  } catch (err) { toast(err.message); }
}

export function setupEditor() {
  const f = form();
  f.addEventListener('submit', submit);
  $('#editor-delete').addEventListener('click', deleteEditing);
  f.addEventListener('change', (e) => {
    if (e.target.name === 'type' || e.target.name === 'all_day') syncFields();
    if (e.target.name === 'category') fillSubcategories();
  });
  $('[data-close]', f).addEventListener('click', closeEditor);
  dialog().addEventListener('close', () => {
    editing = null;
    if (opener?.isConnected) opener.focus();
  });
}
