// Stato dell'app in memoria. Le viste leggono da qui; ogni modifica passa dall'API.

import { api, ApiError } from './api.js';
import { uid } from './dom.js';
import { eventSortKey } from './dates.js';

const KINDS = {
  member: { path: '/members', key: 'members' },
  event: { path: '/events', key: 'events' },
  task: { path: '/tasks', key: 'tasks' },
  shopping: { path: '/shopping/items', key: 'shopping' },
};

export const state = {
  me: null,
  household: null,
  members: [],
  events: [],
  tasks: [],
  shopping: [],
  loaded: false,
  online: navigator.onLine,
  lastSync: null,
};

const listeners = new Set();
export const subscribe = (fn) => listeners.add(fn);
const emit = (reason) => listeners.forEach((fn) => fn(reason));

function sortAll() {
  state.members.sort((a, b) => a.sort_order - b.sort_order || a.display_name.localeCompare(b.display_name, 'it'));
  state.events.sort((a, b) => eventSortKey(a).localeCompare(eventSortKey(b)));
  state.tasks.sort((a, b) => (a.due_date || '9999').localeCompare(b.due_date || '9999') || a.created_at.localeCompare(b.created_at));
  state.shopping.sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export const memberById = (id) => state.members.find((m) => m.id === id);
export const activeMembers = () => state.members.filter((m) => !m.archived);
export const find = (kind, id) => state[KINDS[kind].key].find((item) => item.id === id);

function replace(kind, entity) {
  const list = state[KINDS[kind].key];
  const index = list.findIndex((item) => item.id === entity.id);
  if (entity.deleted_at) {
    if (index >= 0) list.splice(index, 1);
  } else if (index >= 0) {
    list[index] = entity;
  } else {
    list.push(entity);
  }
  sortAll();
}

/** In caso di conflitto (409) ricarica i dati, così l'utente vede la versione aggiornata. */
async function guard(promise) {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 409 || error.status === 404)) {
      await refresh().catch(() => {});
    }
    if (error instanceof ApiError && error.status === 401) {
      state.me = null;
      emit('logout');
    }
    throw error;
  }
}

export async function loadSession() {
  try {
    const me = await api('GET', '/me');
    state.me = me;
    state.household = me.household;
    return true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return false;
    throw error;
  }
}

export async function login(username, password) {
  const me = await api('POST', '/auth/login', { body: { login: username, password } });
  state.me = me;
  state.household = me.household;
  await refresh();
  emit('login');
}

export async function logout() {
  await api('POST', '/auth/logout').catch(() => {});
  Object.assign(state, { me: null, household: null, members: [], events: [], tasks: [], shopping: [], loaded: false });
  emit('logout');
}

export async function refresh() {
  const [household, members, events, tasks, shopping] = await Promise.all([
    api('GET', '/household'),
    api('GET', '/members'),
    api('GET', '/events'),
    api('GET', '/tasks'),
    api('GET', '/shopping/items'),
  ]);
  Object.assign(state, { household, members, events, tasks, shopping, loaded: true, lastSync: new Date() });
  sortAll();
  emit('refresh');
}

/**
 * La chiave di idempotenza va riusata per ogni nuovo tentativo della stessa creazione
 * (l'editor la tiene finché resta aperto): se la prima richiesta era arrivata, il server non duplica.
 */
export async function create(kind, data, idempotencyKey = uid()) {
  const send = () => api('POST', KINDS[kind].path, { body: data, idempotencyKey });
  const entity = await guard(send().catch((error) => {
    if (error instanceof ApiError && error.status === 0) return send();
    throw error;
  }));
  replace(kind, entity);
  emit('change');
  return entity;
}

export async function update(kind, entity, patch) {
  const updated = await guard(api('PATCH', `${KINDS[kind].path}/${entity.id}`, { body: patch, version: entity.version }));
  replace(kind, updated);
  emit('change');
  return updated;
}

/** Elimina e restituisce una funzione che annulla l'eliminazione. */
export async function remove(kind, entity) {
  const deleted = await guard(api('DELETE', `${KINDS[kind].path}/${entity.id}`, { version: entity.version }));
  replace(kind, deleted);
  emit('change');
  return async () => {
    const restored = await guard(api('POST', `${KINDS[kind].path}/${deleted.id}/restore`, { version: deleted.version }));
    replace(kind, restored);
    emit('change');
  };
}

export async function clearCheckedShopping() {
  const cleared = await guard(api('POST', '/shopping/items/clear-checked'));
  cleared.forEach((item) => replace('shopping', item));
  emit('change');
  return async () => {
    for (const item of cleared) {
      const restored = await api('POST', `/shopping/items/${item.id}/restore`, { version: item.version });
      replace('shopping', restored);
    }
    emit('change');
  };
}

export async function updateHousehold(patch) {
  state.household = await guard(api('PATCH', '/household', { body: patch, version: state.household.version }));
  emit('change');
}

export async function importLegacy(data) {
  const result = await api('POST', '/import/local', { body: data, idempotencyKey: `import-${uid()}` });
  await refresh();
  return result;
}

export function setOnline(online) {
  state.online = online;
  emit('online');
}
