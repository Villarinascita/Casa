# INSIEME — Assistente personale e familiare

Documento funzionale e tecnico · versione 1.0 · 11 settembre 2026

## 1. Stato delle decisioni

Questo documento raccoglie le richieste della famiglia e propone una base tecnica implementabile. «Confermato» indica una richiesta dell'utente; «proposto» indica una scelta progettuale ancora da validare in implementazione; «realizzato» si riferisce esclusivamente al prototipo locale.

| Elemento | Stato |
|---|---|
| Famiglia come ambito iniziale, lavoro completo in futuro | Confermato |
| Due genitori, una bambina e tutti i nonni | Confermato |
| Tablet touch Windows e PWA su Android/iPhone | Confermato |
| Accesso fuori casa e dati condivisi | Confermato, da implementare |
| NAS Synology DS923+, RAM 32 GB, quattro dischi da 4 TB | Dichiarato dall'utente; capacità lorda 16 TB, capacità utile e RAID non verificati |
| LLM e trascrizione cloud, niente modello locale | Confermato per LLM; trascrizione cloud proposta |
| Audio come ingresso principale | Priorità confermata |
| Foto, PDF, Gmail e moduli manuali | Confermato |
| WhatsApp | Richiesto; modalità di integrazione da verificare |
| PostgreSQL e backend Python/FastAPI | Proposta tecnica |
| Agno, ex Phidata, come framework agente | Raccomandazione, non ancora installato né definitivamente approvato |
| Hermes Agent | Alternativa valutata, non installata |

## 2. Obiettivo del prodotto

L'utente invia un audio naturale e l'assistente consulta, crea e aggiorna elementi reali dell'organizzazione familiare. L'interfaccia permette di controllare e correggere ciò che viene salvato. La memoria conversazionale non sostituisce il database.

Esempio: «Giovedì alle tre viene il tecnico, resta a casa mia moglie, ricordaglielo la sera prima e aggiungi le pile alla spesa». Il sistema deve risolvere data e persona, creare l'appuntamento, assegnare la presenza, programmare un avviso consentito e aggiungere il prodotto. Se non è chiaro se siano le 03:00 o le 15:00, deve chiarire prima del salvataggio dell'appuntamento.

Non deve dichiarare eseguita un'azione fallita o ancora in attesa. Risposte quali «Dov'è mia moglie?» devono specificare che il luogo deriva dal calendario, con fonte e ultimo aggiornamento. Nessuna localizzazione GPS è stata richiesta.

## 3. Persone, ruoli e privacy

- Genitori: account distinti, elementi personali e condivisi, gestione degli incarichi.
- Bambina: membro familiare senza account obbligatorio.
- Nonni: membri associabili agli impegni; account e notifiche soltanto se abilitati. I nomi reali e i legami si configurano nell'app.
- Tablet: sessione condivisa limitata alle informazioni familiari; accesso ai dati personali tramite autenticazione separata.
- Ogni accompagnamento distingue andata e rientro, persona responsabile e stato da assegnare/confermato.
- L'identità del parlante deriva dalla sessione autenticata. Sul tablet si sceglie il profilo; nessun riconoscimento vocale biometrico è previsto.

Ruoli proposti: amministratore familiare, adulto, collaboratore (es. nonno), dispositivo condiviso. La visibilità è condivisa, privata o limitata a membri selezionati. I controlli devono avvenire sul server anche nelle ricerche e nelle chiamate dell'agente.

## 4. Funzioni e aree

| Area | Funzioni previste |
|---|---|
| Oggi | Appuntamenti, preparativi, responsabilità, prossime scadenze e proposte da verificare |
| Calendario | Giorno/settimana/mese, ricorrenze, eccezioni, partecipanti, luogo, tempi di viaggio e disponibilità |
| Attività | Responsabile, scadenza, sottoattività, priorità, ricorrenze e completamento |
| Bambina | Scuola, nuoto, ginnastica artistica, gare/saggi, materiale, quote, certificati e accompagnamenti |
| Sport adulti | Nuoto e altro sport della mamma; ginnastica del papà; orari da configurare |
| Spesa | Liste condivise, quantità, categorie, prodotti abituali, completamento e annullamento |
| Casa | Tecnici, consegne, manutenzioni e persona che deve essere presente |
| Bollette | Utenza, fornitore, importo, scadenza, allegato e stato del pagamento |
| Auto | Due schede veicolo, documenti, assicurazione, bollo, revisione, tagliandi, pneumatici, chilometri e storico |
| Documenti e note | Foto/PDF, estrazione verificabile, archivio, ricerca e scadenze documentali |
| Ricorrenze personali | Compleanni, anniversari, regali e preparativi anticipati |
| Da verificare | Proposte da Gmail, documenti, incongruenze e informazioni mancanti |

Categorie opzionali selezionabili: salute e visite già programmate, abbonamenti, viaggi, animali, menù settimanale. Nessun impegno o dato reale va creato soltanto perché plausibile.

Bollette: distinguere da pagare, addebito previsto e pagamento verificato. Un'email o la data di addebito non provano automaticamente il pagamento. Scadenze auto e sanitarie non devono essere dedotte senza fonte o regola verificata.

## 5. Configurazione progressiva

L'app deve permettere di scegliere aree, aggiungere familiari, assegnare auto, impostare orari e collegare servizi. Nessun lungo questionario obbligatorio. Ogni area richiede soltanto i dati necessari e segnala quelli mancanti.

Ingresso unico: Parla, Scrivi, Scatta foto, Carica file, Compila manualmente. Il microfono è l'azione principale. Interfaccia italiana, controlli touch di almeno 44–48 px, etichette accessibili, navigazione da tastiera e supporto a riduzione movimento.

## 6. Flusso audio e agente

1. Registrazione esplicita dal dispositivo con indicazione microfono attivo e possibilità di annullare.
2. Upload autenticato; validazione dimensione, durata e formato.
3. Trascrizione cloud; conservazione temporanea dell'audio secondo preferenze.
4. Interpretazione usando data corrente, fuso, identità, membri e contesto autorizzato.
5. Produzione di un piano strutturato di azioni con argomenti validati.
6. Chiarimento soltanto per dati indispensabili, ambiguità o azioni che richiedono conferma.
7. Esecuzione tramite API applicative, con idempotenza e registrazione dell'esito.
8. Riepilogo delle azioni salvate e di quelle non eseguite. Risposta vocale facoltativa.

Stati: ricevuto, in trascrizione, in interpretazione, attesa chiarimento, pronto, in esecuzione, completato, parziale, fallito, annullato. Un nuovo tentativo non deve duplicare le azioni già completate.

Esecuzione diretta per azioni chiare e reversibili come aggiungere una voce spesa. Conferma per cancellazioni importanti, modifiche estese a ricorrenze, estrazioni documentali e invii esterni non già autorizzati. «Annulla l'ultima operazione» usa azioni compensative e verifica che altri utenti non abbiano modificato gli stessi elementi.

Strumenti minimi dell'agente: search_events, get_availability, create_event, update_event, assign_transport, create_task, complete_task, add_shopping_items, create_reminder, search_documents, propose_document_fields. Sono contratti applicativi da costruire, non funzionalità già installate.

## 7. Stack tecnico proposto

| Livello | Tecnologia / scelta |
|---|---|
| Frontend iniziale | HTML, CSS e JavaScript esistenti; nessuna migrazione a framework necessaria per il primo flusso |
| PWA | Manifest, service worker, HTTPS; test installazione e notifiche sui dispositivi finali |
| API | Python + FastAPI, validazione Pydantic, contratto OpenAPI |
| Agente | Agno dietro un adattatore sostituibile; Hermes resta alternativa |
| Modello e voce | Provider cloud da scegliere; chiavi esclusivamente lato server |
| Database | PostgreSQL, versione supportata fissata in fase di implementazione |
| Accesso dati | SQLAlchemy e migrazioni Alembic |
| File | Directory privata sul NAS, metadati nel DB, accesso solo tramite API autorizzata |
| Lavori asincroni | Worker Python separato, coda persistente PostgreSQL per il carico familiare iniziale |
| Distribuzione | Container Compose sul NAS, compatibilità DSM/Container Manager da verificare |
| Accesso remoto | Reverse proxy HTTPS, dominio e certificato; autenticazione prima dell'esposizione |

Schema logico: PWA → API autenticata → servizi applicativi → PostgreSQL e archivio NAS. API → coda → worker → trascrizione/LLM/Gmail/canali. L'agente richiama i servizi applicativi, senza accesso SQL o shell generico ai dati familiari.

## 8. Database: modello logico

**Database scelto come proposta: PostgreSQL.** Nessun database server è attualmente installato nel progetto. Il prototipo usa localStorage nel browser.

Convenzioni: chiavi UUID; importi NUMERIC(12,2) con valuta; timestamp TIMESTAMPTZ; date senza ora DATE; metadati variabili JSONB senza sostituire relazioni e vincoli. Oggetti modificabili con created_at, updated_at, version e autore. Entità familiari con household_id e regole di visibilità.

| Tabella | Campi principali e relazioni |
|---|---|
| households | id, name, timezone, locale, settings |
| users | id, login, password_hash o identità esterna, stato |
| household_users | household_id, user_id, role; coppia univoca |
| members | id, household_id, user_id opzionale, display_name, relationship |
| entity_shares | household_id, entity_type/id, member_id, permission; integrità gestita con tabelle specifiche ove necessario |
| events | id, household_id, title, start_at/end_at, all_day, start_date/end_date, timezone, location, status, visibility, owner_id, source_id, version |
| event_participants | event_id, member_id, role |
| recurrence_rules | id, event_id, rrule, timezone, valid_until |
| recurrence_exceptions | series_id, original_occurrence, cancelled, override_event_id; coppia univoca |
| transport_assignments | event_id/occurrence, leg, responsible_member_id, status, travel_minutes |
| tasks | id, household_id, title, assignee_id, due_at, status, priority, parent_id, event_id |
| shopping_lists | id, household_id, name |
| shopping_items | id, list_id, label, quantity, unit, category, checked_at, checked_by |
| assets | id, household_id, kind, label, owner_member_id; casa e veicoli |
| vehicles | asset_id, plate, make, model, registration_date, odometer_km |
| maintenance_records | id, asset_id, performed_on, odometer_km, description, amount, next_date, next_km |
| bills | id, household_id, asset_id, supplier, amount, currency, due_date, payment_state, document_id |
| documents | id, household_id, storage_key, original_name, mime, size, sha256, owner_id, visibility, extracted_fields, extraction_status |
| document_links | document_id e riferimenti applicativi validati alle entità |
| notes | id, household_id, title, body, owner_id, visibility |
| source_connections | id, household_id, user_id, provider, encrypted_credentials_ref, status, cursor |
| source_messages | id, connection_id, external_id, received_at, document_id; connection_id/external_id univoci |
| proposals | id, household_id, source_id, proposed_actions, uncertain_fields, status, reviewed_by |
| conversations / messages | id, household_id, user_id, role, text, timestamp, retention_until |
| action_batches / actions | id, request_id, actor_id, tool, arguments, status, result, idempotency_key, compensation |
| reminders | id, household_id, target, recipient_id, scheduled_at, channel, status |
| notification_preferences | user_id, timezone, quiet_hours, channels, escalation_policy |
| jobs | id, kind, payload_reference, run_at, status, attempts, lease_until, last_error |
| notification_outbox | id, reminder_id, recipient_id, channel, status, provider_id, attempt_count |
| audit_entries | id, household_id, actor_id, action, entity_id, timestamp, changed_fields |

Il modello è una specifica, non una migrazione SQL pronta. Indici principali: eventi per famiglia/data, task per responsabile/stato/scadenza, job per stato/run_at, reminder per stato/scheduled_at, messaggi per connessione/external_id. Vincoli temporali impediscono fine precedente all'inizio. Controlli di relazione impediscono riferimenti tra famiglie diverse. Le regole RLS possono aggiungere difesa al controllo API, ma vanno implementate e testate esplicitamente.

Fuso iniziale proposto Europe/Rome, configurabile e da confermare. Eventi ricorrenti definiti in ora locale con fuso; le occorrenze vanno calcolate correttamente durante i cambi d'ora. Eventi per tutto il giorno usano date, senza conversioni arbitrarie in mezzanotte UTC.

## 9. API applicative proposte

Prefisso /api/v1. Tutte autenticate salvo login e health minima. La famiglia e l'autore si ricavano dalla sessione autorizzata.

| Endpoint | Scopo |
|---|---|
| POST /auth/login; POST /auth/logout; GET /me | Sessione e identità |
| GET/POST /members | Configurazione famiglia |
| GET/POST /events; PATCH/DELETE /events/{id} | Calendario, con controllo versione |
| POST /events/{id}/exceptions | Modifica singola occorrenza |
| GET/POST /tasks; PATCH /tasks/{id} | Attività |
| GET/POST /shopping-lists/{id}/items | Spesa |
| POST /assistant/audio | Upload e avvio processo asincrono, risposta 202 con job_id |
| POST /assistant/messages | Richieste testuali e chiarimenti |
| GET /assistant/runs/{id} | Stato, azioni ed esiti |
| POST /action-batches/{id}/confirm oppure /undo | Conferma o annullamento consentito |
| POST /documents; GET /documents/{id} | Upload e accesso autorizzato |
| GET /proposals; POST /proposals/{id}/review | Verifica estrazioni |
| POST /connections/gmail/start; GET /connections/gmail/callback | Collegamento OAuth |
| DELETE /connections/{id} | Revoca e scollegamento |

Errori strutturati con code, message, field_errors e request_id. Idempotency-Key per le creazioni da agente e retry client. Aggiornamenti con version/If-Match; conflitti restituiti come 409 senza sovrascrivere silenziosamente.

## 10. Documenti, Gmail e calendario esterno

Foto/PDF: limiti configurati di peso/pagine, verifica MIME e contenuto, nomi di storage generati dal server, hash per duplicati, scansione file e parser isolati. Il worker estrae testo e usa visione cloud quando necessario. Ogni campo mantiene fonte e incertezza; l'originale resta consultabile. I dati vengono applicati dopo conferma.

Gmail: OAuth per ogni casella, lettura soltanto, mittenti/etichette configurabili, token cifrati e revocabili, sincronizzazione incrementale e deduplicazione. Scope esatti, requisiti del progetto Google e modalità push/polling da verificare prima dell'implementazione. Nessun invio o cancellazione email nel primo rilascio.

Calendario nutrizionista: acquisire dettagli API/ICS del sistema esistente. Importare solo occupato fino a, sede ed eventuale indisponibilità, senza nomi pazienti. Conservare external_id, versione e last_synced_at; gestire spostamenti, cancellazioni e fonte non raggiungibile.

WhatsApp: integrazione richiesta ma non garantita dal solo framework. Verificare canale ufficiale, numero, costi, regole messaggistica e supporto audio/gruppi. Nessun accesso presunto alle chat private e nessuna scelta non ufficiale approvata.

## 11. Affidabilità, sicurezza e gestione cloud

Sessioni cookie HttpOnly/Secure, protezione CSRF, rate limit, password hash robusto se login locale e possibile secondo fattore. Chiavi e token fuori da frontend e repository; cifratura token con chiave separata dal DB. Download autorizzati; documenti privati esclusi dal service worker.

L'agente vede soltanto dati consentiti. Email e documenti sono contenuti non attendibili, non istruzioni. Strumenti con schema rigoroso, controlli server, limiti di esecuzione e costi. Log senza token, audio o testo integrale dei documenti per impostazione predefinita.

Ogni operazione multipla registra successi e fallimenti. Le modifiche DB correlate possono essere atomiche; gli invii esterni passano da outbox con retry. Non si promette consegna esattamente una volta: si usano chiavi di deduplicazione e stato provider quando disponibile.

I promemoria funzionano tramite worker persistente; l'LLM non è necessario per inviare un avviso già programmato. Rispetto ore silenziose, preferenze e destinatari. Il NAS spento o senza internet può ritardare gli avvisi: recupero dei job e indicazione di ritardo alla ripartenza.

## 12. PWA, offline e sincronizzazione

Cache iniziale solo dell'interfaccia. Offline futuro: snapshot autorizzato degli impegni e coda delle modifiche spesa, con stato visibile «da sincronizzare». IndexedDB per la coda; ID idempotenti e versioni server per riconciliare. Operazioni IA, Gmail e upload restano in attesa di connessione. Cancellazione cache privata al logout.

Installazione, microfono, formati audio e push da testare su Windows, Android e iPhone reali. HTTPS necessario in distribuzione; permessi richiesti nel contesto dell'azione. Nessuna garanzia di comportamento identico fra browser senza test.

## 13. NAS, backup e operatività

Servizi previsti: frontend/reverse proxy, API, worker, PostgreSQL. Volumi separati per database, documenti e backup. Porte DB non esposte a internet. Risorse, immagini compatibili e versione DSM da verificare sul NAS prima del deployment; i 32 GB non costituiscono da soli una verifica di installabilità.

Backup proposto: giornaliero DB e allegati con manifest coerente; copia separata dal NAS; cifratura e rotazione. RAID non sostituisce il backup. Obiettivi iniziali da concordare: perdita massima di 24 ore di dati e ripristino entro una giornata. Prova effettiva di ripristino prima dell'uso quotidiano.

Monitorare ultimo sync Gmail/calendario, job falliti, spazio disco, esiti notifiche, latenza ed uso API. Limite mensile cloud configurabile, con soglie di avviso e comportamento esplicito al raggiungimento del limite. Provider, budget e conservazione audio ancora da scegliere.

## 14. Stato reale del codice

Realizzato: prototipo HTML/CSS/JavaScript, navigazione, calendario mensile, inserimento appuntamenti, attività e spesa, completamento/eliminazione, configurazione membri incluse etichette provvisorie dei nonni, selezione aree, export JSON, manifest e service worker di base.

File: index.html, styles.css, app.js, sw.js, manifest.webmanifest, icon.svg, server.cjs, package.json. Avvio npm start su http://localhost:4173, bind locale 127.0.0.1. Dati nel localStorage insieme-v1, isolati per browser/origine. Lo script npm run check esegue controlli di sintassi; non certifica i flussi, il rendering o l'installazione sui dispositivi.

Non realizzati: database server, utenti autenticati, sincronizzazione, audio, LLM/Agno/Hermes, upload documenti, Gmail, WhatsApp, calendario esterno, ricorrenze, notifiche reali e deployment NAS. Il prototipo non è pronto per dati riservati o esposizione pubblica.

## 15. Piano aggiornato: audio al centro

1. Backend minimo, PostgreSQL, autenticazione e migrazioni; API per eventi, attività e spesa.
2. Primo percorso completo audio → trascrizione → agente → azioni salvate → riepilogo, con chiarimenti e retry verificati.
3. Collegamento PWA ai dati condivisi; disponibilità, nonni, accompagnamenti e ricorrenze.
4. Documenti e auto/bollette con estrazione e revisione.
5. Gmail e calendario lavorativo in lettura.
6. Promemoria affidabili, WhatsApp dopo verifica e completamento test PWA.
7. Distribuzione NAS e prova backup/ripristino.

Questa sequenza aggiorna la specifica iniziale: l'audio non è una rifinitura da aggiungere alla fine.

## 16. Test di accettazione essenziali

- Un audio con appuntamento, attività e spesa genera tre azioni corrette; retry non le duplica.
- Un riferimento ambiguo a «nonna» produce una domanda e non assegna la persona sbagliata.
- Un fallimento parziale viene mostrato senza dichiarare tutto completato.
- Un appuntamento ricorrente mantiene l'ora locale al cambio d'ora; modificare un'occorrenza non altera le altre.
- Due utenti aggiornano la spesa senza perdere modifiche; offline e retry sono riconciliati.
- Il tablet e un nonno non accedono a documenti privati neppure tramite API o agente.
- Una bolletta duplicata non crea due scadenze; un addebito previsto non viene marcato pagato.
- Un file poco leggibile rimane in verifica; i campi incerti non sono inventati.
- Un calendario esterno non aggiornato viene dichiarato tale nelle risposte.
- Riavviare il worker non perde promemoria; gli invii già riusciti non vengono ripetuti inutilmente.
- Backup e ripristino recuperano DB, file e collegamenti coerenti.

## 17. Informazioni ancora necessarie

Non impediscono il prototipo, ma servono prima della produzione: nomi e ruoli reali; orari; accessi concessi ai nonni; provider cloud e budget; conferma Agno oppure Hermes; formato calendario lavorativo; caselle Gmail e criteri; modalità WhatsApp; DSM e rete NAS; dominio/accesso remoto; backup; conservazione documenti/audio e orari delle notifiche. La maggior parte dovrà essere raccolta nella configurazione dell'app.

## 18. Riferimenti

Documentazione consultata nella conversazione per il confronto degli agenti:

- Agno: https://docs.agno.com/ — SDK, runtime, API e integrazioni.
- Phidata: https://docs.phidata.com/introduction — passaggio del progetto ad Agno.
- Hermes Agent: https://hermes-agent.nousresearch.com/docs/ — agente, voce, strumenti e gateway.

Versioni, compatibilità e procedure dei servizi devono essere verificate sulla documentazione ufficiale al momento dell'implementazione. Questo documento non certifica integrazioni già funzionanti.
