# Pubblicità nel cestino in automatico — design

Data: 26 settembre 2026 · Stato: approvato da Luca ("Prepara tutto").

## 1. Obiettivo

Luca non vuole scegliere a mano quali email tenere. Hermes, che legge già ogni
email nuova per bollette e appuntamenti, decide anche se è pubblicità pura e in
quel caso la sposta nel cestino di Gmail. Nessuna chiamata in più al modello:
la stessa analisi restituisce un campo in più.

L'elenco manuale "Email da ignorare" (domini o indirizzi) resta come forzatura.

## 2. Regola di decisione (tutte le condizioni)

Un'email nuova va nel cestino automaticamente solo se:

1. l'impostazione `auto_trash_promotions` della famiglia è attiva (default: sì);
2. Hermes risponde `"promo": true` (solo pubblicità, newsletter, offerte,
   marketing — senza ordini, ricevute, fatture, spedizioni, appuntamenti,
   scadenze, avvisi di sicurezza o comunicazioni personali);
3. c'è un segnale tecnico di posta di massa: header `List-Unsubscribe`
   oppure etichetta Gmail `CATEGORY_PROMOTIONS`;
4. l'analisi non ha prodotto nulla: nessuna azione (appuntamento, attività,
   spesa) e nessuna bolletta valida;
5. l'email non è speciale (etichette `STARRED` o `IMPORTANT` di Gmail);
6. il mittente non è nell'elenco `kept_email_senders` (domini o indirizzi,
   stessa corrispondenza dei mittenti bloccati).

Se una qualunque condizione manca, l'email resta in casella come oggi.

Il cestino usa `trash_message` (mai cancellazione definitiva). Senza permesso
`gmail.modify` l'email resta in casella e la connessione mostra "Ricollega
Google" come per i mittenti bloccati; non si registra nulla.

## 3. Dati

- `household.settings["auto_trash_promotions"]`: bool, default `true`.
- `household.settings["kept_email_senders"]`: lista di domini/indirizzi,
  validata come `blocked_email_domains`, max 100.
- Nuova tabella `email_auto_trash`: `id`, `household_id`, `connection_id`,
  `recipient_user_id`, `message_id`, `sender` (indirizzo, max 320),
  `subject` (max 500), `trashed_at`, `reported_at` (nullable). Serve al
  riepilogo e all'elenco in Impostazioni.

## 4. Riepilogo settimanale su Telegram

Il worker, per ogni destinatario con Telegram collegato: se ha righe
`email_auto_trash` non ancora riportate e la più vecchia ha almeno 7 giorni,
invia un messaggio unico con il totale e i conteggi per dominio del mittente
(i 10 più frequenti), poi segna le righe come riportate. Esempio:

> Negli ultimi giorni ho messo nel cestino 58 email pubblicitarie:
> it.jooble.org 25, eu.temuemail.com 14, newsletter.conad.com 3 …
> Sono nel cestino di Gmail per 30 giorni. Se un mittente ti serve scrivimi
> «tieni conad».

## 5. Comando Telegram «tieni»

`tieni <qualcosa>` (anche `/tieni`, maiuscole indifferenti):

- se `<qualcosa>` è un dominio o indirizzo valido, lo si usa così com'è;
- altrimenti si cerca tra i mittenti cestinati automaticamente dalla famiglia
  un dominio che contiene la parola; se ce n'è esattamente uno si usa quello,
  se nessuno o più di uno si risponde chiedendo il dominio preciso.

L'elemento si aggiunge a `kept_email_senders` e si toglie da
`blocked_email_domains` se c'era (chiudendone l'eventuale pulizia). Non si
ripristinano email dal cestino.

## 6. API e frontend

- `HouseholdOut`/`HouseholdPatch`: `auto_trash_promotions`, `kept_email_senders`.
- `GET /household/auto-trashed`: ultime 50 email cestinate in automatico
  (mittente, oggetto, data).
- Impostazioni, sezione "Email da ignorare": interruttore "Metti nel cestino
  la pubblicità da sola", elenco "Mittenti da tenere sempre" e lista delle
  ultime email cestinate con pulsante "Tieni questo mittente".

## 7. Test

- Decisione: ogni condizione della §2 presa singolarmente impedisce il cestino;
  tutte vere → cestino + riga `email_auto_trash`; 403 → nessuna riga.
- `analyze_email`: il prompt chiede `promo`; un `promo` non booleano vale falso.
- Riepilogo: niente prima di 7 giorni; dopo, un messaggio con conteggi e righe
  segnate; destinatario senza Telegram → niente.
- «tieni»: dominio esplicito, parola con una corrispondenza, parola ambigua,
  rimozione dai bloccati.
- API: impostazioni salvate e validate; elenco limitato alla famiglia.

## 8. Fuori scopo

- Pulizia retroattiva della pubblicità già in casella (solo email nuove).
- Ripristino dal cestino.
