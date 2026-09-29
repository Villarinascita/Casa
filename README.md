# Insieme — assistente di famiglia

PWA per coordinare impegni, attività e spesa della famiglia, con dati condivisi tra tablet e telefoni.
Specifica completa, decisioni e piano: [docs/SPECIFICA_COMPLETA.md](docs/SPECIFICA_COMPLETA.md).

## Cosa funziona oggi (v0.3)

- Accesso con account personali (niente registrazione pubblica: gli utenti si creano da riga di comando).
- Familiari con identificativo stabile: rinominarli non rompe gli impegni; si archiviano invece di cancellarli.
- Appuntamenti con ora di inizio/fine o per tutto il giorno, persona responsabile e luogo. Ripetizione giornaliera, settimanale o mensile fino a una data scelta, con promemoria Telegram.
- Attività con scadenza e responsabile; scadute evidenziate. Lista della spesa condivisa con inserimento rapido.
- Calendario mensile con giorni selezionabili; vista «Famiglia» con chi fa cosa e cosa è senza responsabile.
- Modifica di ogni voce, eliminazione con «Annulla», conflitti tra due dispositivi segnalati (mai sovrascritti in silenzio).
- Aggiornamento automatico ogni 30 secondi e al ritorno sull'app; «Oggi» si aggiorna da solo a mezzanotte.
- Esportazione JSON e importazione dei dati della prima versione (localStorage `insieme-v1`).

Questa versione aggiunge il collegamento Telegram per ogni utente, messaggi scritti e vocali (con trascrizione configurata), interpretazione tramite Hermes dedicato, creazione strutturata di appuntamenti/attività/spesa, promemoria Telegram e ripetizione delle attività. Gmail in sola lettura produce proposte da approvare; Calendar sincronizza i calendari selezionati e mostra i conflitti da risolvere. Sul NAS è attiva solo l'API/PWA; le integrazioni esterne non sono ancora collegate ad account reali.

Restano fuori da questo rilascio: documenti, auto/bollette, WhatsApp e sincronizzazione offline in scrittura.

### Appuntamenti ripetuti e promemoria

Nel nuovo appuntamento scegli «Ripeti appuntamento» e «Fino al (compreso)».
La serie genera al massimo 366 appuntamenti indipendenti: modifica, eliminazione e annullamento
riguardano la singola occorrenza. Gli orari delle ripetizioni seguono il fuso della famiglia,
anche al cambio dell'ora; nei mesi più corti si usa l'ultimo giorno disponibile, tornando
al giorno originale nel mese successivo. In Google Calendar vengono sincronizzati come singoli eventi.

«Promemoria Telegram» vale anche per un appuntamento non ripetuto. Il destinatario è il responsabile
se ha un utente associato, altrimenti l'autore. Serve il collegamento Telegram del destinatario
e il worker in esecuzione. Gli eventi per tutto il giorno usano le 09:00 come riferimento;
l'anticipo è espresso in minuti (1 giorno = 24 ore). Gli invii falliti vengono ritentati;
gli avvisi disattivati, eliminati o non più validi dopo uno spostamento vengono annullati.
Gli avvisi scadono alla fine dell'appuntamento, oppure un'ora dopo l'inizio se non ha una fine,
e a fine giornata per gli eventi senza orario. Non vengono recuperati dopo tale scadenza.

Per aggiornare un'installazione esistente, eseguire `alembic upgrade head` dalla cartella `backend`
prima di avviare la nuova API e il worker (migrazione `20260929_01`).

## Struttura

```
frontend/   PWA senza build: index.html, styles.css, sw.js, js/ (moduli ES)
backend/    FastAPI + SQLAlchemy + Alembic, database SQLite in data/insieme.db
docs/       specifica
```

## Avvio in locale

Requisiti: Python 3.11+ e [uv](https://docs.astral.sh/uv/).

```powershell
cd backend
uv sync
uv run alembic upgrade head                                   # crea/aggiorna data/insieme.db
uv run python -m app.cli create-household "Famiglia Rossi"    # crea anche etichette provvisorie dei familiari
uv run python -m app.cli create-user luca --role admin        # chiede la password (min. 10 caratteri)
uv run python -m app.cli create-user anna --role admin
uv run uvicorn app.main:app --host 127.0.0.1 --port 4173
```

Poi apri http://localhost:4173. Documentazione interattiva delle API: http://localhost:4173/api/docs.

Altri comandi: `list-users`, `reset-password <login>`. Configurazione con variabili `INSIEME_*`
(vedi `backend/app/config.py`), per esempio `INSIEME_DATABASE_URL` o `INSIEME_COOKIE_SECURE=true` dietro HTTPS.

Per le integrazioni avvia anche `uv run python -m app.worker` in un secondo processo. Configura le variabili elencate in [.env.example](.env.example); il worker usa il token Telegram e un endpoint API Hermes dedicato. Per Google crea un client OAuth Web con redirect URI `https://<dominio>/api/v1/connections/google/callback`, abilita Gmail API e Google Calendar API, e genera `INSIEME_GOOGLE_TOKEN_KEY` con `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Per i messaggi vocali serve un endpoint di trascrizione compatibile con `multipart/form-data` (`file`, `model`, `language`) che restituisca `{ "text": "..." }`.

Sul NAS usa [compose.yaml](compose.yaml) e la guida [docs/DEPLOY_NAS.md](docs/DEPLOY_NAS.md). La chiave di cifratura e le credenziali devono essere conservate anche nel backup separato.

## Test

I test di regressione del frontend si eseguono dalla radice con `node --test frontend/tests/*.test.mjs`.

```powershell
cd backend
uv run pytest                                                          # API: accesso, isolamento, conflitti, fusi orari…
Get-ChildItem ..\frontend -Recurse -Filter *.js | % { node --check $_.FullName }   # sintassi del frontend
```

## Da telefono o tablet in casa

`--host 0.0.0.0` rende l'app raggiungibile in rete locale all'indirizzo del PC, ma su HTTP semplice i browser
disattivano service worker, installazione PWA e (in futuro) microfono: per l'uso reale serve HTTPS
(reverse proxy sul NAS, oppure Tailscale/mkcert in sviluppo). Non esporre l'app su internet senza HTTPS.

## Note

- Backup: `data/insieme.db` è un unico file. Con l'app avviata usa `sqlite3 data/insieme.db ".backup copia.db"`.
- La cartella del progetto è sincronizzata da OneDrive: meglio spostarla fuori (es. `C:\dev\insieme`) per evitare
  che `.venv` e il database vengano sincronizzati durante l'uso.
- Dopo aver modificato l'elenco dei file del frontend, aggiornare `VERSION` e `ASSETS` in `frontend/sw.js`.
