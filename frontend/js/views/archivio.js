import { html } from '../dom.js';
import { state } from '../store.js';
import { empty, heading } from './common.js';

const DESCRIPTIONS = {
  Auto: 'Due veicoli, documenti, assicurazioni, bollo, revisione e tagliandi.',
  'Casa e bollette': 'Scadenze, pagamenti da verificare e appuntamenti con i tecnici.',
  Bambina: 'Scuola, nuoto, ginnastica artistica e accompagnamenti.',
  Documenti: 'Foto e PDF, lettura assistita e conferma dei dati estratti.',
};

export function render() {
  const areas = state.household?.areas || [];
  return html`
    ${heading('Le informazioni di casa', 'Ogni cosa al suo posto.', 'Aree previste nel progetto. Caricamento ed estrazione dei documenti arriveranno con i prossimi moduli.')}
    ${areas.length ? areas.map((area) => html`<section class="module">
      <div class="eyebrow">Da sviluppare</div>
      <h2>${area}</h2>
      <p>${DESCRIPTIONS[area] || 'Area personalizzata della famiglia.'}</p>
    </section>`) : empty('Nessuna area selezionata. Sceglile dalle Impostazioni.')}`;
}
