// Date del calendario in formato 'YYYY-MM-DD' secondo l'ora locale del dispositivo.

const pad = (n) => String(n).padStart(2, '0');

export const localDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Sempre ricalcolato: il tablet resta acceso per giorni. */
export const today = () => localDate(new Date());

export function parseDate(value) {
  const [y, m, d] = value.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function addDays(value, days) {
  const d = parseDate(value);
  d.setDate(d.getDate() + days);
  return localDate(d);
}

/** Data e ora locali → istante ISO in UTC per l'API. */
export const toInstant = (date, time) => new Date(`${date}T${time}`).toISOString();

export const timeOf = (iso) => {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

export const dayOfInstant = (iso) => localDate(new Date(iso));

export function formatDay(value, options = { weekday: 'short', day: 'numeric', month: 'short' }) {
  return parseDate(value).toLocaleDateString('it-IT', options);
}

export function formatLongToday() {
  return new Date().toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

export function msUntilMidnight() {
  const now = new Date();
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return next - now;
}

/** Primo e ultimo giorno (locali) coperti da un appuntamento. */
export function eventSpan(event) {
  if (event.all_day) return [event.start_date, event.end_date || event.start_date];
  return [dayOfInstant(event.start_at), dayOfInstant(event.end_at || event.start_at)];
}

export const eventOnDay = (event, day) => {
  const [first, last] = eventSpan(event);
  return first <= day && day <= last;
};

/** Chiave di ordinamento: gli eventi di tutto il giorno vengono prima di quelli con orario. */
export const eventSortKey = (event) => (event.all_day ? `${event.start_date}T00:00:00` : new Date(event.start_at).toISOString());

export function eventTimeLabel(event) {
  if (event.all_day) return 'Tutto il giorno';
  return event.end_at ? `${timeOf(event.start_at)}–${timeOf(event.end_at)}` : timeOf(event.start_at);
}
