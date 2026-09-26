# Domini email bloccati — design

Data: 26 settembre 2026 · Stato: approvato da Luca, in attesa di piano di implementazione.

## 1. Obiettivo

Luca indica in Impostazioni i domini da cui non vuole più ricevere email. Per
ogni dominio bloccato:

- le email **future** da quel dominio vanno nel cestino di Gmail appena il
  worker le incontra, **prima** di qualsiasi analisi Hermes (zero costo);
- le email **già presenti** in casella da quel dominio vanno nel cestino
  subito dopo il salvataggio, in background, senza conferma.

Sempre cestino (`messages.trash`, recuperabile 30 giorni da Gmail), mai
cancellazione permanente.

## 2. Permesso Google (prerequisito)

Oggi `backend/app/google.py` chiede lo scope
`https://www.googleapis.com/auth/gmail.readonly`, che non consente di
spostare email nel cestino. Va sostituito con
`https://www.googleapis.com/auth/gmail.modify` (che include la lettura).
Una connessione esistente mantiene i permessi vecchi finché Luca non
ricollega Google da Impostazioni; fino ad allora ogni tentativo di cestino
fallisce con 403.

Comportamento senza permesso: il blocco non deve mai fermare il resto della
sincronizzazione. Se Gmail risponde 403 al cestino, l'email viene comunque
segnata come processata senza analisi (resta in casella) e la connessione
registra in `last_error` un messaggio chiaro ("Ricollega Google per
consentire lo spostamento nel cestino"), visibile già oggi in Impostazioni.
La pulizia retroattiva di quel dominio resta "in corso" e riprova ai giri
successivi, così parte da sola appena il permesso c'è.

## 3. Dati

- **Elenco**: `household.settings["blocked_email_domains"]` (lista di stringhe,
  stesso meccanismo di `areas` e `bill_categories`), default lista vuota.
- **Validazione** (schema Pydantic, lato API): minuscole, spazi tolti, niente
  `@`, almeno un punto, solo caratteri validi di dominio
  (`[a-z0-9.-]`), max 253 caratteri, dedup, max 100 voci. Un valore non
  valido restituisce 422.
- **Nuova tabella `email_domain_cleanups`** (una riga per dominio appena
  bloccato): `id`, `household_id`, `connection_id`, `domain`, `status`
  (`running` | `done`), `page_token`, `trashed_count`, `created_at`,
  `completed_at`. Serve a riprendere la pulizia su più giri del worker.

## 4. Corrispondenza del mittente

Si usa solo l'header `From:` (mai corpo o oggetto). L'indirizzo si estrae con
`email.utils.parseaddr`, il dominio è la parte dopo l'ultima `@`, in
minuscolo. Un dominio bloccato `d` corrisponde se il dominio del mittente è
`d` oppure termina con `.d` (quindi `newsletter.com` blocca
`offerte.newsletter.com` ma non `notnewsletter.com`).

### 4.1 Indirizzi precisi (aggiunta del 26/09)

Oltre ai domini, l'elenco accetta indirizzi completi (`promotion-it@amazon.it`):
corrispondono solo a quell'indirizzo esatto, così si scarta la pubblicità
tenendo ordini e ricevute dello stesso dominio. Stessa lista
(`blocked_email_domains`), stessa pulizia retroattiva (`from:<indirizzo>`).

## 5. Email future

In `gmail_sync.ingest_message`, subito dopo il controllo "già processata" e
prima di chiamare `analyze`: se il mittente corrisponde a un dominio
bloccato, si chiama `POST .../messages/{id}/trash`, si registra
`EmailProcessed` e si ritorna 0. Nessuna chiamata Hermes, nessuna
Proposal/bolletta/evento. `ingest_message` riceve la lista dei domini come
parametro (il worker la legge dalle impostazioni della famiglia, come già fa
per le categorie).

## 6. Pulizia retroattiva

- `PATCH /household` confronta la lista precedente con quella nuova; per
  ogni dominio **nuovo** crea una riga `email_domain_cleanups` (per ogni
  connessione Google della famiglia). Rimuovere un dominio dalla lista non
  ripristina nulla; se era in pulizia, la riga viene marcata `done` e il
  worker smette.
- Nuova funzione `run_domain_cleanups(db, service, now)` chiamata dal worker
  dentro il blocco `if google:`, isolata con try/except come gli altri
  dispatcher: per ogni riga `running`, una pagina di
  `in:inbox from:<dominio>` (max 50), cestino per ciascun messaggio,
  aggiorna `page_token` e `trashed_count`, commit. Quando la pagina non ha
  più risultati né `nextPageToken`, `status=done`. Un errore su un
  messaggio non blocca gli altri.
- Nota: dopo il cestino i messaggi escono da `in:inbox`, quindi la ricerca
  successiva ritorna i restanti; il segnalibro serve solo a non ripartire
  da capo se il giro si interrompe.

## 7. API e frontend

- `HouseholdOut.blocked_email_domains: list[str]`, `HouseholdPatch.blocked_email_domains`.
- `GET /household/email-cleanups`: elenco delle pulizie (dominio, stato,
  quante email spostate), per mostrare l'avanzamento.
- Impostazioni: sezione "Email da ignorare", stessa forma di "Categorie dei
  costi" (domini spuntati + campo "Aggiungi un dominio"), con sotto lo stato
  delle pulizie e un avviso se serve ricollegare Google.

## 8. Test

- Corrispondenza dominio: esatto, sottodominio, falso positivo
  (`notnewsletter.com`), header con nome visualizzato, maiuscole.
- Validazione: `@`, senza punto, caratteri non validi → 422; dedup.
- `ingest_message`: email da dominio bloccato → cestino chiamato, nessuna
  chiamata `analyze`, `EmailProcessed` registrata; 403 dal cestino → nessun
  crash, processata, nessuna analisi.
- PATCH: solo i domini nuovi creano pulizie; rimuovere un dominio chiude la
  sua pulizia.
- `run_domain_cleanups`: pagina con risultati → cestino + contatore; pagina
  vuota → `done`; errore su un messaggio non blocca gli altri.

## 9. Fuori scopo

- Cancellazione permanente.
- Pulsante "blocca mittente" dentro l'app (non esiste una vista delle email).
- Ripristino automatico dal cestino quando si sblocca un dominio.
