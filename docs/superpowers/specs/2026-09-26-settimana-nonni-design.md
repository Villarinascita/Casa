# Settimana dei nonni — design

Data: 26 settembre 2026 · Stato: richiesto da Luca.

- Ruolo `nonno` in `household_users`: accesso con utente e password, sessione di 180 giorni.
- Un accesso `nonno` può usare solo `/me`, `/auth/logout`, `/nonni/week`; tutto il resto è 403.
- `GET /nonni/week?start=`: settimana lunedì–domenica con appuntamenti e attività aperte assegnati ai
  familiari in `household.settings["grandparent_members"]` (ora, cosa, dove, chi).
- Pagina unica a scritte grandi: dalla giornata di oggi alla domenica, poi settimana per settimana.
- Solo l'amministratore crea gli accessi (`POST /household/users`, password generata mostrata una volta)
  e rigenera la password (`POST /household/users/{id}/password`, chiude le sessioni aperte).
- Chi gestisce la famiglia vede l'anteprima da Altro e da Impostazioni (`#nonni`).
