# Doppioni e abitudini — design

Data: 26 settembre 2026 · Stato: approvato da Luca ("fai bene tutto").

## 1. Problema

Dalle email arrivano copie dello stesso impegno con parole diverse ("Inizio
allenamenti GIOCAGYM" / "GIOCA GYM 2026/27: inizio allenamenti"), anche già
presenti nel Google Calendar; Hermes non impara da ciò che Luca scarta.

## 2. Doppioni (`backend/app/dedup.py`)

- Parole: minuscole, senza accenti, solo `[a-z0-9]`, senza parole vuote
  (articoli, preposizioni, "ore", "appuntamento", "evento", "inizio"…),
  radice = prime 6 lettere; si aggiungono le coppie consecutive unite
  ("gioca gym" → "giocagym").
- Somiglianza = parole in comune / parole del titolo più corto.
  Servono almeno una parola comune "significativa" (≥ 4 lettere, non numero).
- **Appuntamento**: si confronta con tutti gli appuntamenti (qualsiasi fonte)
  dello stesso giorno locale.
  - somiglianza ≥ 0,6 → stesso evento. Se gli orari distano più di 60 minuti
    non si crea ma si propone in **Da controllare** (con l'orario già presente
    nel testo); altrimenti si scarta in silenzio.
  - 0,34 ≤ somiglianza < 0,6 → caso dubbio: si chiede a Hermes
    (`same_event`) se è lo stesso; errore di Hermes = non doppione.
- **Attività**: con le attività aperte, somiglianza ≥ 0,75 → doppione.

## 3. Abitudini (`backend/app/habits.py`)

- Tabella `email_feedback` (household, kind, title, sender, verdict
  `kept|discarded`, entity_id, created_at).
- `events.source_sender`, `tasks.source`, `tasks.source_sender` (nuove colonne):
  si sa da quale mittente arriva ciò che viene dalle email.
- Registrazione: eliminare un appuntamento/attività venuto dalle email →
  `discarded` (Annulla lo toglie); proposta ignorata → `discarded`; proposta
  accettata → `kept`.
- Tenuti = `kept` + appuntamenti/attività dalle email non eliminati da più di
  3 giorni.
- Esempi a Hermes: ultimi 30 scartati e 20 tenuti nel prompt di analisi
  ("non proporre cose simili a…", "cose utili come…").
- Mittente scartato sempre: ≥ 3 scarti dallo stesso dominio e nessun tenuto →
  niente appuntamenti/attività da quel dominio (le bollette sì).
- I 245 elementi eliminati nella pulizia del 26/09 diventano esempi `discarded`.

## 4. Pulizia dei doppioni esistenti

Stesse regole su tutto il calendario e sulle attività aperte: si tiene la voce
inserita da Luca o da Google Calendar, altrimenti quella con il titolo più
completo; le altre si eliminano (recuperabili).

## 5. Test

Somiglianza (esempi reali), ingestione (doppione silenzioso, orario diverso →
proposta, dubbio → Hermes, attività simili), registrazione e annullamento
del feedback, regola del mittente, esempi nel prompt.
