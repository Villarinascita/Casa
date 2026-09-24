# Preparazione del NAS Synology per Insieme

Il repository contiene un'immagine per l'API/PWA e un worker separato. Il codice è stato distribuito sul NAS; HTTPS e le credenziali delle integrazioni restano da configurare.

## Stato del NAS al 24 settembre 2026

### Nomi sul NAS (progetto personale, separato da quello di lavoro)

| Cosa | Nome |
| --- | --- |
| Cartella condivisa DSM | `DOCKER PERSONALE` (`/volume1/DOCKER PERSONALE`) |
| Progetto | `/volume1/DOCKER PERSONALE/INSIEME`, compose `insieme-personale` |
| Container | `INSIEME-PERSONALE-API`, `INSIEME-PERSONALE-WORKER`, `HERMES-PERSONALE-CHAT`, `HERMES-PERSONALE-EMAIL` |
| Rete / immagine | `NET.PERSONALE` / `insieme-personale:local` |

I container di lavoro (`hermes`, `mcp-gestionale`, `N8N-LAVORO`, ...) e la cartella `DOCKER LAVORO` non vengono toccati.

- DSM 7.3.2 su DS923+. `INSIEME-PERSONALE-API` è healthy e gira da `/volume1/DOCKER PERSONALE/INSIEME`. La vecchia installazione `/volume1/insieme` e l'archivio `insieme-v0.3.tar.gz` sono conservati in `/volume1/DOCKER PERSONALE/_ARCHIVIO` (eliminabili dopo qualche giorno di verifica, insieme all'immagine `insieme:local`).
- L'API risponde a `http://127.0.0.1:4173/api/v1/health` **dal NAS**; la porta è associata solo a `127.0.0.1`. Database SQLite e migrazioni (`20260924_02`) sono nella directory `data`. Non c'è ancora un reverse proxy HTTPS, né una famiglia o un account applicativo. Il file `.env` sul NAS è vuoto.
- Il worker non è avviato: mancano token Telegram, endpoint/chiave di trascrizione e credenziali OAuth Google. Le istanze Hermes dedicate sono predisposte in `compose.hermes.yaml`, ma non avviate.
- `credenziali-locali.txt` è ignorato da Git. L'archivio sorgente trasferito al NAS non contiene credenziali.

1. Copiare il progetto in `/volume1/DOCKER PERSONALE/INSIEME`, creare la directory `data` e renderla scrivibile dall'UID `10001` usato dai container. Evitare una cartella sincronizzata da OneDrive per il database SQLite.
2. Copiare `.env.example` in `.env` e compilare le variabili. `INSIEME_PUBLIC_URL` deve essere l'URL HTTPS che la famiglia apre; `INSIEME_GOOGLE_TOKEN_KEY` va generata una sola volta e conservata anche nel backup.
3. Configurare il reverse proxy DSM verso `127.0.0.1:4173`, con certificato TLS valido. Il client OAuth Google Web deve avere come redirect esatto `<INSIEME_PUBLIC_URL>/api/v1/connections/google/callback`. Abilitare Gmail API e Calendar API. Le autorizzazioni richieste sono lettura Gmail, eventi Calendar e elenco dei calendari.
4. Avviare `docker compose up -d --build`. Il servizio API applica le migrazioni all'avvio. Creare famiglia e utenti con `docker compose exec api .venv/bin/python -m app.cli create-household "Famiglia"` e `docker compose exec api .venv/bin/python -m app.cli create-user nome --role admin`. Il worker resta inattivo finché non sono pronti token Telegram e configurazione Hermes; avviarlo con `docker compose --profile integrations up -d`.
5. Avviare Hermes con profili API dedicati per Insieme. Impostare `INSIEME_HERMES_URL` e `INSIEME_HERMES_EMAIL_URL` agli indirizzi raggiungibili dal worker, con chiavi distinte (`INSIEME_HERMES_API_KEY` e `INSIEME_HERMES_EMAIL_API_KEY`). `host.docker.internal` potrebbe non essere disponibile su DSM. Creare due profili/modelli separati (`insieme`, `insieme-email`) così questa app non usa la memoria dell'altro progetto. Il backend verifica l'identità Telegram e applica gli schemi dati; Hermes interpreta soltanto.
   Sul NAS si può usare [compose.hermes.yaml](../compose.hermes.yaml): crea due istanze Hermes con volumi separati e senza porte pubblicate, lasciando intatto il container dell'altro progetto. Preparare `.env.hermes-chat` e `.env.hermes-email` da [.env.hermes.example](../.env.hermes.example), con chiavi API diverse, poi impostare nel `.env` di Insieme `INSIEME_HERMES_URL=http://hermes-chat:8642`, `INSIEME_HERMES_EMAIL_URL=http://hermes-email:8642` e le rispettive chiavi. Avviare con `docker compose -f compose.yaml -f compose.hermes.yaml --profile integrations up -d` quando anche il token Telegram è pronto.
6. Aprire Impostazioni nell'app: collegare Telegram con il codice temporaneo, quindi Google via OAuth. Scegliere filtro Gmail, calendari completi o in modalità «solo occupato» e il calendario predefinito per gli appuntamenti creati in Insieme. Le proposte Gmail richiedono una decisione esplicita.

Il worker usa il polling Telegram; il token del bot deve essere esclusivo per questo processo. Non avviare due worker con lo stesso token. La sincronizzazione Gmail e Calendar viene riprovata periodicamente; l'ultimo errore Google è visibile nelle impostazioni. Gli eventi di calendario vengono letti in una finestra mobile di circa un anno prima e dopo la data corrente. I promemoria accumulati durante un'interruzione vengono inviati al riavvio se esiste il collegamento Telegram.

Per il backup, fermare temporaneamente API e worker oppure usare l'API backup di SQLite; conservare `data/insieme.db` e la chiave di cifratura in un luogo separato dal NAS. Provare un ripristino su un'istanza separata prima dell'uso quotidiano. La pubblicazione esterna va fatta solo dopo la verifica del reverse proxy HTTPS e degli account reali.
