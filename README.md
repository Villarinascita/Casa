# Insieme — assistente di famiglia

Prima base interattiva, senza dipendenze: `npm start`, poi http://localhost:4173. Verifica sintattica: `npm run check`.

Funzioni attuali: calendario mensile, appuntamenti con persona e luogo, attività assegnate, lista spesa, completamento ed eliminazione con conferma, impostazioni dei familiari e delle aree, esportazione JSON. Dati inizialmente vuoti e salvati nel localStorage del browser: NON sincronizzati tra dispositivi. Non inserire qui documenti riservati: questa versione non ha autenticazione. Le notifiche non vengono ancora inviate.

Manifest e service worker preparano la PWA e la consultazione offline dopo il primo accesso. Installazione e compatibilità richiedono verifica sui dispositivi finali e HTTPS in distribuzione.

Gmail, WhatsApp, LLM, estrazione documenti, audio, account, ricorrenze e NAS sono previsti e non ancora collegati. Nessuna credenziale richiesta nel frontend.

Vedi docs/PROGETTO.md per requisiti e sviluppo successivo.
