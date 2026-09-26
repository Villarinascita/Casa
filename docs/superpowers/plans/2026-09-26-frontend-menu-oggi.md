# Frontend fase 1 (menu, Oggi, Da controllare) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Riorganizzare la PWA Insieme secondo `docs/superpowers/specs/2026-09-26-frontend-menu-oggi-design.md`.

**Architecture:** Vanilla ES modules (`frontend/js`), rendering a stringhe con `html```; nuove rotte in `main.js`; stili nuovi in un foglio separato `frontend/layout.css` caricato dopo `styles.css` (che contiene modifiche dell'utente non ancora in git e non va toccato). Backend FastAPI: tre endpoint in `routers/proposals.py`.

**Tech Stack:** FastAPI, SQLAlchemy, pytest; JS moduli ES senza build; Chrome headless per le verifiche a schermo.

## Global Constraints

- Non modificare né committare `frontend/styles.css`, `frontend/icon.svg`, `frontend/manifest.webmanifest`, `.impeccable.md`; `frontend/index.html` si committa solo con le proprie modifiche (senza la riga `theme-color` dell'utente).
- Colori/stile attuali invariati; controlli touch ≥ 46 px; testi secondari ≥ 14 px.
- Rotte esistenti conservate: `#oggi #calendario #attivita #spesa #archivio #famiglia #impostazioni`; nuove `#controllare #altro`.
- Telefono ≤ 850 px: barra in basso Oggi · Calendario · + · Da fare · Costi; Altro in alto a destra.
- Mai finestre `alert/confirm` del browser.
- `sw.js`: aggiungere i nuovi file ad `ASSETS` e alzare `VERSION`.

---

### Task 1: Backend — filtro, riepilogo e arretrati delle proposte

**Files:** Modify `backend/app/routers/proposals.py`; Test `backend/tests/test_proposals_api.py` (nuovo).

- `GET /proposals?status=pending|accepted|rejected` (facoltativo).
- `GET /proposals/summary` → `{"pending": int, "stale": int}`; stale = pending con `created_at < now - 30 giorni`.
- `POST /proposals/reject-stale` body `{"days": int = 30, ge=7}` → rifiuta le pending più vecchie della famiglia con `audit(db, ctx, "review", p, {"status": "rejected", "bulk": True})`, ritorna `{"rejected": n}`.
- Le route statiche vanno dichiarate prima di `/{proposal_id}/review` (nessun conflitto: metodi/percorsi diversi).
- Test: filtro; summary con proposte di due famiglie e date diverse; reject-stale che tocca solo pending vecchie della famiglia e registra audit; `days=3` → 422.

### Task 2: Store e navigazione

**Files:** `frontend/js/store.js`, `frontend/js/main.js`, `frontend/index.html`, `frontend/layout.css` (nuovo), `frontend/js/views/altro.js` (nuovo), `frontend/sw.js`.

- `state.review = { proposals: 0, stale: 0, conflicts: 0 }`; `refresh()` chiama in più `/proposals/summary` e `/calendar/conflicts` con `Promise.allSettled` (errori ignorati); export `reviewCount()`.
- `ROUTES` con `nav` (voce di menu) separata dalla rotta: NAV = oggi, calendario, attivita (label «Da fare»), archivio (label «Costi»), altro. `NAV_OF = { spesa: 'attivita', famiglia: 'altro', impostazioni: 'altro', controllare: 'oggi' }`.
- Menu laterale con badge `reviewCount()` su Oggi. Barra in basso `#tabbar` (in index.html) resa da `renderChrome()` con 5 posizioni (+ al centro → `openEditor({type: defaultTypeForRoute()})`, `archivio` → tipo `bill`). Pulsante `#more` (Altro) in intestazione, visibile solo su telefono.
- `altro.js`: link grandi a Famiglia, Impostazioni; pulsante Esci.
- `layout.css`: aside sticky 100dvh senza puntino; `.meta` 14 px; su ≤ 850 px nasconde `aside nav`, mostra `#tabbar` fisso in basso, `#more`, nasconde `#add`, `main` padding-bottom 110 px, toast sopra la barra.

### Task 3: Oggi (proposta A)

**Files:** `frontend/js/views/oggi.js`, `frontend/layout.css`.

- Sezioni come nella spec §3; helper puri in `oggi.js`: `deadlines(day)` (costi non pagati con scadenza ≤ day+7 e attività aperte con scadenza ≤ day), `weekTotal(bills)`.
- Linea ORA: tra gli appuntamenti con fine (o inizio) < ora e gli altri; gli appuntamenti tutto il giorno in cima.
- Tablet: griglia `.today-grid` a 3 colonne > 1150 px, 2 colonne 851–1150, 1 su telefono.

### Task 4: Da controllare

**Files:** `frontend/js/views/controllare.js` (nuovo), `frontend/js/views/impostazioni.js` (rimuovere le due sezioni e le funzioni `loadProposals`/`loadConflicts`), `frontend/layout.css`.

- Carica `/proposals?status=pending` e `/calendar/conflicts`; filtri Tutto/Email/Calendario in stato locale del modulo; schede con titolo leggibile per `kind` (shopping: «Aggiungere "X" alla spesa?», event: «Nuovo appuntamento: X», task: «Nuova attività: X»).
- Scheda Arretrati se `state.review.stale > 0`: primo tocco mostra conferma inline («Sì, ignora N» / «No»), poi `POST /proposals/reject-stale`.
- Dopo ogni azione ricarica la lista e `refresh()`.

### Task 5: Elimina nella scheda, Costo come tipo, Da fare a schede

**Files:** `frontend/index.html` (radio Costo, campi costo, pulsante `#editor-delete`), `frontend/js/editor.js`, `frontend/js/views/common.js` (via `deleteButton`), `frontend/js/views/archivio.js` (via modulo, righe apribili), `frontend/js/views/attivita.js`, `frontend/js/views/spesa.js` (schede Attività | Spesa), `frontend/layout.css`.

- Editor: tipo `bill` con category/supplier/amount/due_date; in modifica mostra «Elimina» → chiude, `remove(kind, entity)`, toast con Annulla.
- Righe costo: `button.item-open data-action="edit" data-kind="bill"`; pulsante stato invariato; `main.js handleAction` gestisce `edit` per `bill` (già generico tramite `find`).

### Task 6: Verifica e rilascio

- `node --check` su tutti i moduli; suite pytest; screenshot headless telefono/tablet di oggi, controllare, attivita, spesa, archivio, altro e scheda in modifica; correzioni; commit con `git add` espliciti (index.html tramite indice costruito da HEAD + sole modifiche proprie); deploy NAS.
