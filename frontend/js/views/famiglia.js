import { html } from '../dom.js';
import { addDays, eventSpan, today } from '../dates.js';
import { activeMembers, state } from '../store.js';
import { empty, eventRow, heading, list, sectionHead, taskRow } from './common.js';

const upcoming = (event, day) => eventSpan(event)[1] >= day;

export function render() {
  const day = today();
  const weekEnd = addDays(day, 7);
  const openTasks = state.tasks.filter((t) => t.status === 'open');
  const unassignedEvents = state.events.filter((e) => !e.member_id && upcoming(e, day) && eventSpan(e)[0] <= weekEnd);
  const unassignedTasks = openTasks.filter((t) => !t.member_id);

  return html`
    ${heading('La vostra squadra', 'Chi fa cosa.', 'Impegni e responsabilità di ciascuno. La disponibilità mostrata deriva solo da ciò che è stato inserito nel calendario.')}
    ${unassignedEvents.length || unassignedTasks.length ? html`
      <section class="module attention">
        ${sectionHead('Senza responsabile')}
        ${unassignedEvents.map((e) => eventRow(e, { showDate: true }))}
        ${unassignedTasks.map(taskRow)}
      </section>` : ''}
    ${activeMembers().map((member) => {
      const events = state.events.filter((e) => e.member_id === member.id && upcoming(e, day)).slice(0, 3);
      const tasks = openTasks.filter((t) => t.member_id === member.id);
      return html`<section class="module">
        ${sectionHead(member.display_name, member.relation ? html`<span class="chip">${member.relation}</span>` : '')}
        ${list(events, (e) => eventRow(e, { showDate: true }), 'Nessun prossimo impegno registrato.')}
        ${tasks.length ? html`<h3>Attività assegnate</h3>${tasks.map(taskRow)}` : ''}
      </section>`;
    })}
    ${activeMembers().length ? '' : empty('Nessun familiare configurato. Aggiungili dalle Impostazioni.')}`;
}
