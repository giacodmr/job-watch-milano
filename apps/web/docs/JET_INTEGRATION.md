# Integrazione Jet-inspired e D1 reale locale

Data: 2026-10-30. Branch dedicato `codex/jet-real-data-integration`; PR Draft verso main, senza merge remoto.

## Fonti e confini verificati

- Main iniziale: `b3540152d55b455dd485b167978e92a914a85fc7`; main ricontrollato e integrato prima della consegna: `0b2984a669c4d0dae0b3b666945855c6cda86627` (merge della safety PR #28 da parte dell’utente).
- Base funzionale PR #25, aperta: `b84d7786e977602830f0c88b7afe5b47dc2da16d`. Stessa implementazione di exporter/importer, schema 4, checkpoint CAS, alias, query paginata, filtri, storia osservata e provenienza.
- Safety PR #28, nel frattempo integrata dall’utente in main: `1e53cd1ff9bfd073fa6b08d0c463094e44a45e5d`. I suoi strumenti sono ricevuti da main senza modificarli; nessuna privatizzazione avviata da questa integrazione.
- Reference visiva approvata PR #29, aperta/Draft: `43029d1a9e706a42f8be3f7dd261e2705dfa1e23`. App e CSS della reference sono stati renderizzati separatamente per il confronto; nessun dataset demo è stato portato nell'app integrata.
- Master Product Spec privato v1.1 letto localmente: requisiti funzionali preservati come vincoli/backlog. La richiesta corrente rende la PR #29 autorevole per la grafica; la vecchia palette Electric non viene reintrodotta. Il documento privato non viene copiato nel repository pubblico.

Il confronto fra main della Fase 1 (`3661d7a`) e main attuale comprende Fineco/PayPal, relativo dispatch collector, test/probe/workflow upstream e aggiornamenti dei dati operativi. Non cambiano codec memoria, identità/alias, pipeline state, proiezioni, Daily, worker, bridge o le autorità di regole/aziende/routing. Main è stato integrato nel solo branch di lavoro; il diff verso main non modifica Python, collector, dati operativi o workflow produttivi. Le PR sorgente non sono state modificate da questo incarico. Il successivo main 0b2984a aggiunge soltanto safety tooling/documentazione/CI: fonti allowlist operative invariate. D1 resta correttamente dichiarato allo SHA b3540152, senza una nuova importazione ridondante per un commit di soli strumenti.

## Mappa implementata

`App.tsx` usa la shell della #29 (sidebar, brand originale, workspace, breadcrumb, menu mobile, palette e navigazione). `components.tsx` conserva icone outline originali e componenti della reference. `Dashboard.tsx` e `Opportunities.tsx` leggono il Worker; `JobDetail.tsx` mantiene letture di dettaglio/history/provenienza della #25 in un drawer desktop e una vista mobile a pieno schermo. `shared/` contiene solo DTO puri; il browser non importa servizi server o dati del repository.

Nuovo `GET /api/dashboard`, senza parametri e senza mutation, chiama `getDashboard(db)` indipendente da HTTP, utilizzabile da un futuro adapter MCP. Legge un solo checkpoint CONFIRMED e vincola tutte le query al relativo snapshot. Il browser confronta l'ID con `/api/snapshot`; in caso di differenza mostra errore/riprova, non combina dati di snapshot diversi. Nessun endpoint MCP o servizio cloud attivo.

Definizioni dei quattro contatori:

- Opportunità attive: lifecycle NEW/STILL_OPEN/UPDATED.
- Da analizzare: `needs_analysis=1` proiettato da Python, incluse attese tecniche; non equivale al numero di packet pronti.
- Candidature inviate: decisioni effettive APPLIED nello snapshot; **non** è un tracker candidature con fasi, colloqui o promemoria.
- Fonti in catalogo: righe `source_versions` dello snapshot; non certifica copertura, schedulazione o salute delle fonti.

Nessun checkpoint → metriche null e `—`, non zero. Errori → dati nascosti e riprova. Una importazione incompleta non pubblica staging. Evidenza Dashboard: al massimo cinque offerte aperte, senza hard exclusion, segnalabili o con scelta INTERESTED/TO_REVIEW, escluse APPLIED/NOT_INTERESTED; i flag sono quelli del motore. Ordine `first_seen_at DESC`, poi fit DESC e identità come spareggio. Non si usano last_updated, euristiche di alias o un nuovo modello di matching.

Explorer conserva i filtri server e i cursori della #25. Le viste rapide applicano soltanto combinazioni dei filtri esistenti: Segnalabili, Da valutare, Interessanti, Candidate, Scartate da te e tutto l'inventario. Una nuova visita apre le segnalabili aperte; deep link preesistenti sono rispettati. L'inventario completo e i filtri avanzati mantengono reperibili scarti deterministici, semantici, personali e identità chiuse/unknown. Ricerca, filtri e paginazione sono nell'URL; chiusura del drawer conserva focus, scroll e pagina.

## Confronto visivo e differenze deliberate

Preservati i colori base `#19231b`, `#182319`, `#f7f9f5`, `#ffffff`, `#e1e7de`, `#f1f4ed`, `#d8ed97`, focus `#386b44`, font stack locale, sidebar 250/221px e menu mobile al breakpoint 720px, pannelli, bordi, raggi, spaziature e struttura Dashboard. Nessuna libreria di design, font remoto, nuovo asset di terzi o dipendenza aggiunta.

Differenze dalla demo #29 necessarie ai contratti reali:

- Rimossi badge demo, dati fittizi e KPI vuoti in presenza di dati confermati; testi e definizioni dei contatori sono espliciti.
- Tabella con i tre assi lifecycle/assessment/decisione, fit e batch invece di una priorità inventata. Filtri completi e viste rapide, provenienza e paginazione richiedono più spazio verticale della demo a sei righe.
- Dettaglio reale in drawer (richiesto dal Master Spec e dalla base funzionale), con storico e fonte, anziché scheda dimostrativa inline. Quattro azioni pill visibili ma disabilitate; link ufficiale da apply/canonical realmente importato.
- Alcuni testi secondari resi più scuri per contrasto. Menu mobile con background inert, focus trap/Escape e ritorno focus. Drawer con scroll del corpo separato e background bloccato; correzione del wrapping del pulsante Chiudi.

La composizione della Dashboard segue la #29 approvata, incluso il pannello di salute laterale che si impila su mobile. Il monitor orizzontale del precedente brief Electric non viene introdotto unilateralmente.

## Verifiche effettive

- Node 24.15.0/npm 11.12.1 già disponibili; `npm ci` PASS, zero vulnerabilità segnalate. Lockfile e dipendenze invariati.
- `npm run check`: **42 test Vitest PASS** in 3 file, incluso wrapper dei 10 unittest exporter sintetici; TypeScript strict e build PASS. Tre nuovi test D1/Worker coprono metriche mancanti/staging, ordinamento/precedenza scelte, sola lettura, input strict, no-store e confine locale.
- `npm run db:migrate:local` due volte: schema 4 già applicato, nessuna migrazione pendente in entrambe. Nessuna migrazione nuova o riscritta rispetto alla #25.
- `npm run worker:check`: PASS, soltanto `wrangler deploy --dry-run`, nessun upload/deploy.
- Import reale tramite CLI della #25 dal commit main sopra: checkpoint revisione 2, **5.470 identità**; snapshot precedente conservato. Primo tentativo interrotto con codice redatto LOCAL_SYNC_FAILED dopo 846 chunk; ripresa riuscita con 919 chunk applicati e 846 riconosciuti come replay. Nessun reset del DB. Causa del primo errore non attribuita senza evidenza; durante l'import sono state osservate anche risposte locali 503 correttamente mostrate dalla UI. Dopo la conferma letture regolari e zero staging.
- Replay successivo dello stesso bundle: **0 scritture**, 0 chunk applicati, revisione invariata. Bundle locale privato e ignorato; nessun payload operativo in build, fixture, commit, PR o artifact CI.
- Browser effettivo: **1440×1000**, **768×900**, **390×844**, **320×800 CSS** (dimensioni lette dal DOM, con compensazione dello zoom preesistente del browser). Confrontate Dashboard e Opportunità con la #29 renderizzata separatamente; verificati tabella, drawer desktop/mobile, ricerca senza corrispondenze/reset, paginazione, stato loading, errore reale/riprova, provenienza e review importate. Verificati menu mobile, Shift+Tab/Escape, ritorno focus e scroll, skip link da tastiera e quattro azioni disabilitate. Nessun overflow orizzontale del documento; scorrimento della sola tabella.
- Empty state verificato anche su **un secondo D1 locale effimero vuoto**, schema 4, senza caricare fixture nell'app e senza cancellare il DB persistente. API pronte e assenza di snapshot restano stati distinti.
- Applicate frontend-design e job-watch-ui-direction; review con [Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md) recuperate il 2026-10-30 e checklist vercel:react-best-practices. Corrette le osservazioni di contrasto, focus, scroll e wrapping; nessuna indicazione generica ha sostituito la reference approvata.

Le schermate con dati reali sono conservate soltanto fuori da Git in una directory privata locale, non caricate nella PR pubblica. L'evidenza CI remota va verificata sullo SHA head della Draft, separatamente dai risultati locali.

## Avvio e limiti reali

Comandi di base in README. La preview verificata in questa sessione usa **http://127.0.0.1:8790/** perché un vecchio processo occupava 8787; nessuna configurazione di porta versionata è cambiata:

```sh
cd apps/web
node node_modules/wrangler/bin/wrangler.js dev --local --ip 127.0.0.1 --port 8790
```

Lo stesso D1 persistente rimane in `.wrangler/state/v3`. Le GET non eseguono import, fetch GitHub o collector. L'aggiornamento dei dati resta manuale a SHA esplicito; nessuna sync live viene dichiarata. Restano validi i limiti di budget/bootstrap della Fase 1; l'override usato è esclusivamente locale, non una gestione di quota cloud.

**Non disponibili:** scrittura/undo decisioni, tracker candidature/colloqui/promemoria, note e confronto, rianalisi arbitraria, gestione aziende/ATS, auth remota, salvataggio privato di preferenze fra dispositivi, colonne configurabili permanenti, ordinamenti avanzati e filtri per dati non esposti (RAL, seniority, esperienza, Tier). Nessun bottone simula successo; sidebar futura e azioni pill sono disabilitate. I filtri URL persistono al reload dello stesso URL e non sono spacciati per preferenze utente salvate. Nessun localStorage usato come persistenza operativa.

Motivazioni libere, sintesi AI testuali e JD non vengono ricostruite o aggiunte al DTO: vengono dichiarate non disponibili. Rimangono consultabili soltanto campi strutturati, storico osservato e link alle fonti autorizzate. Nessuna OpenAI API, costo aggiuntivo, accesso cloud, dato produttivo modificato, merge GitHub o deploy.
