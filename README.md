# Insieme — assistente di famiglia

PWA per coordinare impegni, attività e spesa della famiglia, con dati condivisi tra tablet e telefoni.
Specifica completa, decisioni e piano: [docs/SPECIFICA_COMPLETA.md](docs/SPECIFICA_COMPLETA.md).

## Cosa funziona oggi (v0.2)

- Accesso con account personali (niente registrazione pubblica: gli utenti si creano da riga di comando).
- Familiari con identificativo stabile: rinominarli non rompe gli impegni; si archiviano invece di cancellarli.
- Appuntamenti con ora di inizio/fine o per tutto il giorno, persona responsabile e luogo.
- Attività con scadenza e responsabile; scadute evidenziate. Lista della spesa condivisa con inserimento rapido.
- Calendario mensile con giorni selezionabili; vista «Famiglia» con chi fa cosa e cosa è senza responsabile.
- Modifica di ogni voce, eliminazione con «Annulla», conflitti tra due dispositivi segnalati (mai sovrascritti in silenzio).
- Aggiornamento automatico ogni 30 secondi e al ritorno sull'app; «Oggi» si aggiorna da solo a mezzanotte.
- Esportazione JSON e importazione dei dati della prima versione (localStorage `insieme-v1`).

Non ancora presenti: assistente vocale/LLM, ricorrenze, promemoria, documenti, Gmail, WhatsApp, deploy sul NAS.

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

## Test

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
