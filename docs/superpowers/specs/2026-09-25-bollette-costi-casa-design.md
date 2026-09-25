# Bollette e costi di casa — design

Data: 25 settembre 2026 · Stato: approvato da Luca, in attesa di piano di implementazione.

## 1. Obiettivo

Insieme legge già le email tramite Gmail + Hermes e ne ricava proposte di
appuntamenti/attività/spesa da confermare. Questa funzione aggiunge un
secondo tipo di estrazione, con un modello di fiducia diverso: le **bollette
e i costi di casa** vengono creati **subito**, senza passare da una
conferma, categorizzati (Bollette, Auto e assicurazione, Altro, più quelle
che l'utente aggiunge), con promemoria Telegram e una pagina che mostra
tutto ciò che c'è da pagare.

Riferimento di prodotto: `docs/SPECIFICA_COMPLETA.md` prevedeva già
un'area "Bollette" (utenza, fornitore, importo, scadenza, stato del
pagamento) e la regola: *"Un'email o la data di addebito non provano
automaticamente il pagamento"*. Questo design la implementa, scegliendo
deliberatamente di creare la voce subito ma **senza mai marcarla pagata
in automatico**.

## 2. Modello dati

Nuova tabella `bills` (SQLAlchemy `Bill(HouseholdEntity, Base)`, stesso
pattern di `Task`/`Event`: `id`, `household_id`, `created_by`, `created_at`,
`updated_at`, `deleted_at`, `version`):

| Campo | Tipo | Note |
|---|---|---|
| `category` | `String(60)` | testo libero, validato contro l'elenco categorie della famiglia lato API |
| `title` | `String(180)` | es. "Bolletta luce", "Assicurazione auto" |
| `supplier` | `String(180)`, opzionale | es. "Enel", "Unipol" |
| `amount` | `Numeric(10,2)`, opzionale a livello di database | facoltativo per una voce inserita a mano; l'estrazione automatica da email non crea mai una bolletta senza importo (vedi §3) |
| `currency` | `String(3)` | fisso `"EUR"` per ora |
| `due_date` | `Date`, opzionale | può mancare |
| `payment_state` | `String(20)` | `da_pagare` (default) / `addebito_previsto` / `pagato` |
| `source_sender` | `String(320)`, opzionale | mittente dell'email di origine, se creata da email |
| `source_subject` | `String(500)`, opzionale | oggetto dell'email di origine |
| `found_reminder_sent_at` | `DateTime UTC`, opzionale | promemoria "trovata" già inviato |
| `due_reminder_sent_at` | `DateTime UTC`, opzionale | promemoria "in scadenza" già inviato |

Vincoli: `payment_state IN (...)`, indice su `(household_id, payment_state,
due_date)` per la pagina costi e per il worker che cerca le scadenze
vicine.

Categorie della famiglia: **non** una tabella a parte. Seguono lo stesso
schema già usato per le "aree" (`household.settings["bill_categories"]`,
JSON dentro la colonna `settings` già esistente su `households`), default
`["Bollette", "Auto e assicurazione", "Altro"]`, modificabile da
Impostazioni con lo stesso meccanismo con cui oggi si modificano le aree
(`PATCH /me`).

Migrazione Alembic: una nuova tabella, nessuna modifica a tabelle
esistenti.

## 3. Estrazione dalle email

Nessuna nuova chiamata a Hermes: si estende la stessa chiamata che oggi
`HermesClient.analyze_email` già fa per ogni messaggio Gmail (una per
email, come oggi — non raddoppia il costo OpenRouter).

- Il prompt di sistema guadagna un secondo blocco di istruzioni e la lista
  delle categorie configurate dalla famiglia (passata come parametro).
- La risposta JSON guadagna una chiave `bills` accanto alla `actions` già
  esistente: `{"actions": [...], "bills": [{"category", "title",
  "supplier", "amount", "due_date"}, ...]}`.
- Categoria: deve essere presa dall'elenco fornito; se non è chiaro quale,
  usa `"Altro"`. Mai inventare una categoria nuova (l'utente le aggiunge
  da Impostazioni quando vuole).
- Se manca un dato indispensabile per dare senso alla voce (nessun
  importo individuabile), il prompt istruisce Hermes a ometterla piuttosto
  che indovinare.
- `gmail_sync.ingest_message` guadagna un secondo ramo accanto a quello
  che già crea `Proposal`: per ogni voce in `bills`, valida i campi
  (nuovo schema Pydantic `BillIn`) e crea direttamente una riga `Bill` con
  `payment_state="da_pagare"`. Nessuna `Proposal` coinvolta per le
  bollette — è la differenza di fiducia decisa con l'utente.
- Un errore di validazione su una singola bolletta (es. importo non
  numerico) si comporta come già corretto in questa sessione per le
  `actions`: si scarta quella voce, si continua con le altre, il messaggio
  resta comunque segnato come processato (niente retry infinito).

## 4. Promemoria Telegram

Non si riusa `ReminderDelivery`/`Task` (è legata 1:1 a `Task.id`,
cambiarla per supportare due tipi di destinatario è più rischioso che
utile per due soli tipi di avviso). Si usano invece i due timestamp già
descritti sul modello `Bill`, controllati da una nuova funzione
`dispatch_bill_reminders(db, send, now)` chiamata dal worker accanto a
`run_google_once`:

1. **Trovata**: per ogni `Bill` con `found_reminder_sent_at IS NULL`,
   invia un messaggio e imposta il timestamp. Succede al più presto al
   giro del worker successivo alla creazione.
2. **In scadenza**: per ogni `Bill` con `due_date` non nulla,
   `payment_state != 'pagato'`, `due_reminder_sent_at IS NULL` e
   `due_date <= oggi + 3 giorni`, invia un messaggio e imposta il
   timestamp.

Destinatario: sempre l'utente proprietario della `GoogleConnection` da cui
è nata la bolletta (`connection.user_id`), tramite lo stesso
`ChannelLink` Telegram già usato per i promemoria delle attività. Se
l'utente non ha ancora collegato Telegram, il promemoria resta "da
inviare" e riparte al giro successivo (stesso pattern già usato per i
promemoria attività quando manca il collegamento).

## 5. API

Nuovo router `bills`, stesso pattern generico già usato per
`tasks`/`shopping` (`build_router` + `Resource`): `GET/POST /bills`,
`PATCH/DELETE /bills/{id}` con controllo versione (`If-Match`), più un
campo extra scrivibile `payment_state` (stesso meccanismo di
`apply_extras` già usato per lo stato dei task). Creazione manuale e
correzione (importo, categoria, scadenza) passano da qui; la creazione
automatica da email chiama direttamente il modello, non l'endpoint HTTP
(come già fa `gmail_sync` per gli altri tipi).

`GET /me` guadagna `bill_categories` accanto ad `areas`; `PATCH /me`
accetta `bill_categories` con la stessa validazione (dedup, max 30 voci).

## 6. Frontend

La pagina "Casa e documenti" (`frontend/js/views/archivio.js`), oggi uno
stub con testo segnaposto, diventa la pagina reale dei costi:

- Totale da pagare in evidenza in alto (somma di `da_pagare` +
  `addebito_previsto`, non conta `pagato`)
- Elenco ordinato per scadenza, raggruppato per categoria
- Per ogni voce: importo, fornitore/titolo, scadenza, stato con controlli
  per cambiarlo (da pagare → addebito previsto → pagato) ed eliminarla
- Pulsante "Aggiungi" per creare una voce a mano, stesso stile del form
  già usato per le attività
- Gestione delle categorie personalizzate in Impostazioni, accanto a dove
  oggi si gestiscono le aree

## 7. Test

- `test_gmail_proposals.py` (o nuovo `test_bills.py`): estrazione bollette
  da un'email finta, verifica categoria/importo/scadenza, verifica che un
  messaggio senza importo non crei nulla, verifica che un errore di
  validazione su una bolletta non blocchi le altre né le `actions` della
  stessa email.
- `test_worker.py`: `dispatch_bill_reminders` invia "trovata" una sola
  volta, invia "in scadenza" solo entro 3 giorni e solo se non pagata, non
  invia nulla per una bolletta già pagata.
- Test API `bills`: CRUD, controllo versione, isolamento tra famiglie
  (pattern già seguito dagli altri router).

## 8. Fuori scopo (deliberatamente)

- Nessuna lettura di conti correnti o altre fonti oltre l'email.
- Nessuna gestione multi-valuta.
- Nessun allegato/PDF della bolletta collegato (previsto dalla specifica
  generale come modulo "Documenti", separato).
- Nessun collegamento a un'entità "veicolo" con targa/documenti: "Auto e
  assicurazione" qui è solo una categoria di spesa, non un asset.
