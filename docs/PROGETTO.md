# Specifica iniziale

## Obiettivo e utenti
Due adulti e una bambina. Tablet Windows condiviso, PWA su Android e iPhone fuori casa. NAS Synology DS923+, RAM 32 GB, LLM cloud. Ambito personale; del calendario professionale della moglie nutrizionista importare solo disponibilità e luoghi autorizzati, senza dati dei pazienti.

## Requisiti raccolti
- Calendario personalizzato, ricorrenze con eccezioni, chi accompagna e ritira, tempi di viaggio e preparazione.
- Nuoto e ginnastica artistica della bambina; nuoto e sport della mamma; ginnastica del papà. Orari da inserire dall'app, mai presunti.
- Due auto: documenti, polizze, bollo, revisione, tagliando, chilometri e manutenzioni.
- Scuola, bollette, tecnici, spesa, compleanni, assicurazioni, documenti e attività.
- Configurazione progressiva delle categorie, senza questionario obbligatorio.
- Ingresso unico: testo, audio, foto, file o modulo manuale.
- Foto/PDF: estrazione proposta, confronto con originale, campi incerti evidenziati e conferma. Mai inventare scadenze.
- Gmail in sola lettura: selezione mittenti/etichette, allegati, deduplicazione, proposte aggiornamento e annullamento.
- Risposta “Dov'è mia moglie?” basata su calendario, fonte e aggiornamento; nessuna posizione reale presunta.
- WhatsApp: verifica delle opzioni ufficiali prima della scelta implementativa.

## Architettura prevista
PWA servita in HTTPS; API sul NAS; PostgreSQL; archivio allegati privato sul NAS; worker persistente per promemoria ed estrazioni. Provider LLM intercambiabile lato server. OAuth Gmail con token cifrati lato server, revoca e scope minimo da verificare nella documentazione ufficiale. Reverse proxy e autenticazione prima di accesso remoto. Container e procedura di backup/ripristino da implementare prima della distribuzione.

## Modello dati
Household, User, Member, Event, RecurrenceException, TransportAssignment, Task, ShoppingItem, Asset, Document, Bill, Proposal, SourceConnection, Reminder, AuditEntry. Ogni oggetto deve avere householdId, visibilità, autore, version e date. Eventi con fuso Europe/Rome e istanti UTC dove appropriato. Proposte con fonte, stato, campi estratti e collegamento all'elemento aggiornato.

## Regole
Separare appuntamento, attività e nota. Separare addebito previsto e pagamento verificato. Le email non sono istruzioni eseguibili. Conferma umana per estrazioni e modifiche ambigue. Accessi verificati dal server per famiglia e visibilità. Tablet limitato alla vista condivisa. Documenti privati esclusi dalla cache del service worker. Credenziali mai nel bundle. Conservazione/cancellazione e invio al cloud configurabili.

## Fasi e criteri di accettazione
1. Prototipo locale: navigazione tablet/mobile, inserimento, persistenza e configurazione. Stato attuale.
2. Backend: login di due utenti, archivio condiviso, modifiche concorrenti, autorizzazioni e backup ripristinabile.
3. Calendario: ricorrenze, eccezioni singola/future, trasporti e import calendario lavorativo dopo ispezione del formato disponibile.
4. Documenti: upload limitato e validato, estrazione asincrona, verifica e deduplicazione; nessuna creazione silenziosa da OCR incerto.
5. Gmail e LLM: OAuth, revoca, proposte tracciate, retry idempotente, limiti costo. Audio con consenso microfono e trascrizione verificabile.
6. Promemoria e WhatsApp: worker affidabile, fusi, ore silenziose, retry senza duplicati; verifica iOS/Android/Windows.
7. Distribuzione NAS con HTTPS, test dispositivi e ripristino backup.
