# Frontend fase 1: menu, Oggi e Da controllare — design

Data: 26 settembre 2026 · Stato: approvato da Luca ("Ok") dopo il confronto dei
disegni (https://claude.ai/artifact/LCrtsc7tULBLJQvoDvZNR7, proposta A).

## 1. Problema

L'analisi delle schermate ha mostrato che l'organizzazione nasconde ciò che si
usa ogni giorno: bollette sotto "Casa e documenti", proposte dalle email in
fondo a Impostazioni, menu a 7 voci che su telefono scorre di lato e si taglia,
"Elimina" su ogni riga, Oggi senza costi.

## 2. Navigazione

- Cinque voci: **Oggi · Calendario · Da fare · Costi · Altro**.
- Rotte esistenti conservate (i link salvati continuano a funzionare):
  `#oggi`, `#calendario`, `#attivita`, `#spesa`, `#archivio` (Costi),
  `#famiglia`, `#impostazioni`; nuove `#controllare` e `#altro`.
- Voce attiva: Da fare per `attivita`/`spesa`; Altro per
  `altro`/`famiglia`/`impostazioni`; Oggi per `oggi`/`controllare`.
- "Da fare" apre `#attivita`; in cima ad Attività e Spesa due schede
  (Attività | Spesa) collegano le due pagine.
- **Altro** (`#altro`): elenco di collegamenti grandi a Famiglia, Impostazioni
  ed Esci.
- **Telefono (≤ 850 px)**: barra fissa in basso a 5 posizioni —
  Oggi, Calendario, **+** (Aggiungi, al centro), Da fare, Costi; Altro è
  un pulsante in alto a destra. Il pulsante "Aggiungi" dell'intestazione si
  nasconde. Il contenuto ha spazio in fondo per non finire sotto la barra.
- **Tablet/computer**: barra laterale a tutta altezza (fissa) con le 5 voci.
- Il numero "da controllare" compare come badge sulla voce Oggi.

## 3. Oggi (proposta A)

Dall'alto:
1. Saluto e data.
2. Riquadro giallo **Da controllare** (link a `#controllare`) con il numero e
   il dettaglio "N dalle email · M conflitti"; nascosto se zero.
3. **Oggi**: appuntamenti del giorno in un pannello; gli appuntamenti finiti
   sono attenuati e una linea "ORA hh:mm" separa passato e futuro; se non ce
   ne sono, messaggio vuoto con pulsante "+ Appuntamento".
4. **Scadenze (prossimi 7 giorni)**: costi non pagati scaduti o in scadenza
   entro 7 giorni (importo a destra, scaduti in corallo) e attività aperte
   scadute o in scadenza oggi; sotto, "Da pagare questa settimana: X €"
   (somma dei costi mostrati) che porta a Costi.
5. **Da fare**: attività aperte senza scadenza o in scadenza dopo oggi, max 5,
   con la casella per completarle; link "Tutte".
6. Riquadri piccoli: prodotti da comprare (→ Spesa) e primo impegno di domani
   (→ Calendario).

Su tablet (> 850 px): le sezioni 3, 4+6 e 5 stanno su tre colonne.
Rimosso: la lista "Prossimi 7 giorni" completa (è nel Calendario).

## 4. Da controllare

- Pagina `#controllare`: proposte in attesa dalle email e conflitti del
  calendario, prima uscite da Impostazioni (le sezioni lì spariscono).
- Filtri a pillola: Tutto · Email · Calendario, con i conteggi.
- Ogni voce è una scheda: etichetta del tipo e provenienza, titolo leggibile
  (es. «Aggiungere "Latte" alla spesa?», «Nuovo appuntamento: …»), dettaglio,
  due pulsanti grandi (Aggiungi/Ignora; Tieni Google/Tieni Insieme).
- **Arretrati**: se ci sono proposte in attesa più vecchie di 30 giorni, una
  scheda "N proposte hanno più di 30 giorni" con pulsante "Ignora le più
  vecchie di 30 giorni" (chiede conferma nella scheda stessa, niente
  finestre del browser).
- Server:
  - `GET /proposals?status=pending` filtra per stato (senza parametro: come oggi);
  - `GET /proposals/summary` → `{"pending": n, "stale": m}` (stale: in attesa
    da più di 30 giorni);
  - `POST /proposals/reject-stale` body `{"days": 30}` (min 7) → segna
    `rejected` le proposte in attesa più vecchie, con audit, e restituisce
    `{"rejected": n}`.
- Lo store tiene `state.review = {proposals, stale, conflicts}` aggiornato a
  ogni `refresh()`; un errore su questi conteggi non blocca il resto.

## 5. Elimina nella scheda

- Le righe di appuntamenti, attività e spesa non hanno più "Elimina": si tocca
  la riga per aprire la scheda; la scheda in modifica ha un pulsante
  "Elimina" (secondario, a sinistra) che chiude la scheda, elimina e mostra il
  toast con "Annulla" come oggi.
- **Costo** diventa un quarto tipo della scheda (Appuntamento · Attività ·
  Spesa · Costo) con Categoria, Titolo, Fornitore, Importo, Scadenza; il "+"
  su Costi apre la scheda su Costo. Nella pagina Costi il modulo sempre
  aperto sparisce, le righe si aprono nella scheda (anche per eliminare) e
  il pulsante di stato resta.

## 6. Correzioni visive

- Barra laterale a tutta altezza (sticky) e nessun "puntino" decorativo.
- Testi secondari (`.meta`, sottotitoli) almeno 14 px.

## 7. Test

- Backend (pytest): filtro `status`, `summary` (conteggi e limite famiglia),
  `reject-stale` (solo in attesa, solo più vecchie, solo la famiglia, audit,
  `days` < 7 → 422).
- Frontend: controllo sintattico (`node --check`) di ogni modulo e verifica a
  schermo con Chrome headless su telefono (390×844) e tablet (1280×800) di
  Oggi, Da controllare, Da fare, Costi, Altro, più scheda aperta in modifica.

## 8. Fuori scopo (fase 2)

Costi raggruppati per scadenza con "Pagato", Impostazioni a blocchi,
calendario "agenda" su telefono, email cestinate dentro Da controllare.
