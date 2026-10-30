> Baseline visuale della PR #29. Questo documento conserva il contesto del primo passaggio demo; la successiva integrazione React con dati reali è descritta in [JET_INTEGRATION.md](JET_INTEGRATION.md).

# Job Watch — UI first pass / riferimento Jet HR

## Obiettivo e originalità

Le schermate inviate dall'utente (Dashboard, tabelle, processo di assunzione e layout con sidebar) sono un **riferimento visuale**, non un tema importabile. La pagina HTML Jet HR consegnata è una pagina marketing Webflow con script di terze parti, non il sorgente del prodotto amministrativo mostrato nelle schermate. Nessun file, logo, font proprietario o codice Jet HR è incorporato nella nuova UI.

Il design utilizza un linguaggio originale Job Watch: spazio di lavoro personale, struttura informativa compatta, colori botanici molto contenuti e particolare attenzione alla distinzione fra dati reali, dati sintetici e funzioni non disponibili.

## Scope implementato nel primo passaggio

- Dashboard: navigazione, metrica con valori `—` (non inventati), pannello stato locale derivato da `GET /api/health`, empty state e accesso alla demo.
- Explorer: **sei opportunità sintetiche**, nomi di aziende fittizie, ricerca locale, filtri per località e decisione, reset e pannello dettaglio dimostrativo.
- Sidebar desktop e menu mobile; sezioni future visibilmente disabilitate.
- CSS con design tokens, font stack locale e layout responsive. Non è stato introdotto un pacchetto di componenti o una nuova libreria.
- L'app non legge ancora i job, i dati sensibili o le preferenze del repository operativo.
- Nessuna nuova route API o scrittura. Il contratto di Fase 0 resta valido.

## Scelte UX e dati

- L'Explorer è sempre marcato «Modalità demo» e contiene un avviso esplicito che i job sono inventati.
- Le decisioni `TO_REVIEW`, `INTERESTED`, `APPLIED` nell'Explorer sono etichette sintetiche in memoria locale, **non** decisioni del sistema operativo.
- Fino all'importer della Fase 1, il dashboard non mostra conteggi operativi. Il pannello di salute conserva la logica API della Fase 0; in caso di errore mostra un'istruzione operativa.
- In futuro la UI dovrà leggere esclusivamente snapshot confermati secondo `SYNC_CONTRACT.md`; nessuna sostituzione automatica del dataset demo con dati reali.

## Tokens cromatici di partenza

| Token | Valore | Uso |
|---|---|---|
| Ink | `#19231b` | Testo |
| Dark | `#182319` | Pulsanti primari, marchio originale |
| Canvas | `#f7f9f5` | Sfondo applicazione |
| Surface | `#ffffff` | Pannelli |
| Border | `#e1e7de` | Divider e confini |
| Soft | `#f1f4ed` | Selezione e rilievi discreti |
| Lime | `#d8ed97` | Accento limitato |
| Focus | `#386b44` | Focus da tastiera |

Questi colori sono proposte *Job Watch*, non valori ufficiali di Jet HR.

## Controlli da eseguire

Dopo `cd apps/web && npm ci`:

1. `npm run check` e `npm run worker:check`; `npm run db:migrate:local` se necessario.
2. `npm run dev:api` e `npm run dev` su terminali separati.
3. A 1440px/768px/390px/320px: verificare header, sidebar, scrolling orizzontale solo sulla tabella, wrapping e leggibilità.
4. Da tastiera: tab fra dashboard/explorer, input/filtri, focus visibile, apertura dettaglio; provare anche filtraggio a zero risultati.
5. Controllare `GET /api/health` raggiungibile, non raggiungibile, D1 non inizializzato; nessun KPI operativo inventato.
6. Ricontrollare che nessuna richiesta di scrittura, sincronizzazione o nuovo servizio remoto avvenga dal browser.

**Stato delle verifiche:** implementazione via GitHub connector, senza ambiente Node 24 e dipendenze installate nel container di lavoro. Build, CI e verifica visiva su browser dell'app React non ancora eseguite in questo passaggio; non dichiararle superate finché esiti o screenshot reali non siano disponibili.

## Fasi successive

Dopo review della UI, estrarre i componenti più usati in moduli, integrare la sola lettura del checkpoint D1 dalla Fase 1 e disegnare la scheda vacancy reale usando esclusivamente i contratti esistenti. Separare quest'attività dalle fasi di autorizzazione remota e dei comandi confermati.
