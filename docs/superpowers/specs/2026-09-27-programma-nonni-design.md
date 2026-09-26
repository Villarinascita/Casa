# Programma dei nonni da file — design

Data: 27 settembre 2026 · Stato: approvato da Luca (formati: PDF e Word).

- Caricamento dall'app (Impostazioni › Pagina dei nonni, `POST /nonni/plans` con il file in base64)
  o da Telegram (documento inviato al bot). Testo estratto: `.docx` (paragrafi e tabelle), `.pdf`
  (pypdf), `.txt`; `.doc`, foto e scansioni danno un messaggio chiaro.
- Il worker fa leggere il testo a Hermes (`read_grandparent_plan`): voci con chi, cosa, giorno della
  settimana o data, orari, luogo, fino a quando (default: 30 giugno, fine anno scolastico) e dubbi.
- Conferma: in «Da controllare» (Conferma e inserisci / Scarta) o su Telegram rispondendo «sì» / «no».
- Alla conferma: nonni mancanti creati tra i familiari e aggiunti ai nonni; impegni futuri con fonte
  `nonni` di un programma precedente eliminati (recuperabili); nuovi appuntamenti settimanali fino alla
  data finale (max 500), assegnati al nonno; non vengono inviati a Google Calendar.
- Hermes non raggiungibile: si riprova; risposta inutilizzabile: programma «non leggibile».
