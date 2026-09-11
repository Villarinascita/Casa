import { html } from '../dom.js';
import { today } from '../dates.js';
import { state } from '../store.js';
import { empty, heading, sectionHead, taskRow } from './common.js';

const group = (title, tasks) => (tasks.length ? html`<h3>${title} <span class="count">${tasks.length}</span></h3>${tasks.map(taskRow)}` : '');

export function render() {
  const day = today();
  const open = state.tasks.filter((t) => t.status === 'open');
  const done = state.tasks
    .filter((t) => t.status === 'done')
    .sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''))
    .slice(0, 30);
  return html`
    ${heading('Una cosa alla volta', 'Le cose da fare.', 'Assegna un responsabile e segna ciò che avete completato.')}
    ${sectionHead('Aperte', html`<button type="button" class="primary" data-action="add" data-type="task">＋ Nuova attività</button>`)}
    ${open.length ? html`
      ${group('Scadute', open.filter((t) => t.due_date && t.due_date < day))}
      ${group('Oggi', open.filter((t) => t.due_date === day))}
      ${group('Prossime', open.filter((t) => t.due_date && t.due_date > day))}
      ${group('Senza scadenza', open.filter((t) => !t.due_date))}` : empty('Nessuna attività aperta.')}
    ${done.length ? html`<details class="completed"><summary>Completate di recente (${done.length})</summary>${done.map(taskRow)}</details>` : ''}`;
}
