# Refactor stato vacancy — report finale

Snapshot sorgente: `791eba5e49a14b1b61a302ca22975eb55141f285`. Branch `refactor/job-state-simplification`; nessun merge su main. Misure in byte/MB decimali, sullo stesso snapshot ufficiale: nessuna nuova raccolta live e nessuna decisione GPT inventata per ridurre il backlog.

## 1. Architettura prima e dopo

Prima: quattro current, quattro analysis con storia e lifecycle, quattro registri semantic, quattro surfaced, una user authority globale, quattro queue e quattro cache JD; Daily costruita includendo JD. Anche il priority snapshot Amazon conteneva JD complete.

Dopo: quattro current ufficiali in perimetro + quattro job_memory (semantic/user/surfacing) + una Daily derivata. Queue e analysis soltanto in memoria; worker indipendenti da 1–30 vacancy, fetch JD just-in-time a stdout, conclusione persistita e testo scartato. Archivio JSONL freddo. Amazon mantiene receipt di coverage, metadata/hint e fingerprint, senza JD persistente. `STRUCTURAL_AUDIT.md` contiene la dependency map completa.

## 2. File eliminati e nuovi

Eliminati tutti i **21 file legacy**: `semantic_queue_jw1..jw4.json`, `analysis_results_jw1..jw4.json`, `semantic_jd_cache_jw1..jw4.json`, `semantic_decisions_jw1..jw4.json`, `surfaced_jobs_jw1..jw4.json`, `user_job_decisions.json`. Non rimane alcun reader/writer runtime di questi file.

Nuovi: `job_memory_jw1..jw4.json`, `job_memory.py`, `location_policy.py`, `state_maintenance.py`, `semantic_worker.py`, `state_migration.py`, `state_migration_report.json`, `test_job_memory.py`, `archive/vacancies_2026_09.jsonl`, `archive/vacancies_2026_10.jsonl` e questo report. DAILY/MAINTENANCE/STRUCTURAL_AUDIT, workflow e consumer aggiornati. I report precedenti sono marcati storici.

## 3. Dati migrati

| Batch | Semantic | Surfacing | User | Current prima → dopo filtro/chiusure |
|---|---:|---:|---:|---:|
| JW1 | 352 | 23 | 37 | 922 → 347 |
| JW2 | 1039 | 92 | 171 | 1313 → 951 |
| JW3 | 113 | 5 | 6 | 179 → 136 |
| JW4 | 223 | 13 | 12 | 483 → 271 |

Totale: **1.727 semantic**, **133 surfaced**, **226 user** nelle memorie e **1 user** integralmente preservata nel receipt unresolved, per **227/227** scelte. Distribuzione originale: 147 NOT_INTERESTED, 64 TO_REVIEW, 11 INTERESTED, 5 APPLIED. L'unresolved è la decisione NOT_INTERESTED su ION Group, esclusa dalla company authority. Nessuna scelta cancellata o reinterpretata.

I valori JSON delle decisioni semantic/user e tutti i campi originali surfaced sono stati confrontati con Git. Tutti i first_seen noti sopravvivono in current, memoria o archivio. Ogni current non chiuso e in perimetro è presente nel nuovo current; le aggiunte priority sono riconciliate separatamente. **11 alias** storici di identità con scelte utente sono risolti via URL pubblico, senza eliminare chiavi originali. **2417 record** compatti in archivio (1.29 MB).

## 4. Invarianti e validazione

Passati: preflight, input validation, **77 unittest**, sync reale, strict state validation, due sync consecutivi con worklist byte-identica, simulazioni packet/commit/replay e isolamento su JW1/JW2/JW3/JW4, simulazioni London/Luxembourg e filtro prima del fetch.

Coperti permanentemente: projection senza analysis; queue derivata; no JD in memory/current; surfaced e user roundtrip; NOT_INTERESTED su fingerprint/ID nuovi; APPLIED senza re-review; reminders sotto 72 ore e senza estensione della finestra; closed fuori dal current; nessuna lettura archive nel runtime; indipendenza worker anche quando gli altri batch mancano; priorità; stabilità Daily; equivalenza migration fixture e unresolved; transazione append con recovery senza duplicazione; patch ritardate/replay; source/batch failure isolation e guardrail fit/salary/L.68/seniority.

Le simulazioni di selezione sui dati reali restituiscono packet di JW1=10, JW2=10, JW3=3, JW4=7. Non viene dichiarato un JD fetch live evitato dopo averlo realmente eseguito: la misura sotto è controfattuale sullo snapshot esistente.

## 5. Geography implementata

`allowed_locations` in `companies_job_watch_v2.json`, indipendente dai vecchi campi descrittivi `locations` e tier. London: Mastercard, Amazon, Prima Assicurazioni, American Express, Uber, Revolut, Satispay, EssilorLuxottica, Snam, Webuild, Campari Group (alias Campari). Luxembourg: Amazon, Mastercard, Ferrero. Nessun altro employer abilitato automaticamente. Scope italiano precedente conservato.

Filtro nei loop inventory metadata dei collector, nel confine di normalizzazione/reconciliation e nuovamente prima di queue/worker/Daily. La query Yello usa soltanto le location autorizzate quando i suoi filtri sono verificabili. Varianti London/England/UK/Greater London e Luxembourg City riconosciute; omonimi USA/Canada/East London South Africa esclusi. Multi-location italiane valide restano in perimetro.

Soglie reporting ora separate per geography, con valori **già esistenti**: Milano/Roma 70, London/Luxembourg 80. Nessun aumento arbitrario.

## 6. Beneficio misurato

| Metrica | Prima | Dopo |
|---|---:|---:|
| File vacancy state hot, incluso Daily | 26 | 9 |
| Hot bytes, incluso priority receipt Amazon | 28,731,988 | 9,302,000 |
| Hot MB | 28.73 | 9.30 |
| Daily bytes | 985,545 | 153,920 |
| London open nel funnel standard | 1563 | 596 |
| Luxembourg open nel funnel standard | 118 | 118 |
| Semantic pending | 263 | 76 |
| Full JD nella Daily | 88 | 0 |

Hot ridotto del **67.6%**, Daily del **84.4%**. Il conteggio file hot esclude config, health, archivio e report; includendo il priority receipt è 27 → 10. Il byte size include lo stesso receipt sia prima sia dopo.

Eliminati **7,879,615 byte di full-JD text** dal percorso persistente: 3,211,714 dalle cache e 4,667,901 da Amazon, oltre alle copie che la vecchia Daily incorporava. È testo UTF-8, non una stima di token e non rimozione dalla storia Git.

Simulazione: **967 London** e **0 Luxembourg** fuori allowlist possono essere fermate prima dell'enrichment; **187** delle righe già presenti nella vecchia coda avrebbero richiesto JD/review inutili e ora non entrano nei worker. Inventory leggeri globali possono restare inevitabili. Il debito residuo è 76, non zero artificiale; i worker possono drenarlo senza bloccare tutto il reporting mattutino.

## 7. Compromessi e rischi residui

- I campi di evidenza semantic già necessari ai guardrail sono preservati, comprese review chiuse. La memoria resta circa 6 MB complessivi; GPT legge packet e Daily, non quelle memorie integrali.
- I timestamp/count legacy surfaced sono soltanto quelli effettivamente disponibili: quando manca storia precedente, primo/ultimo noto coincidono e count parte da 1. Nessun messaggio chat ricostruito artificialmente. Le categorie di rifiuto storiche mancanti restano mancanti; nuove decisioni richiedono feedback/categoria.
- Alcuni career site espongono la location soltanto nel dettaglio: quella richiesta resta necessaria, ma non parte un successivo JD enrichment né review fuori policy.
- Il journal e il lock proteggono processi nello stesso checkout. Tra checkout diversi serve integrazione Git, con pubblicazione Actions serializzata. I worker scrivono file disgiunti; publication rigenera sul main aggiornato in caso di gara e non duplica un nuovo archive mensile non ancora tracciato.
- L'upgrade testabile resta per restore/rebase di vecchi snapshot e regression fixture. Nessun compatibility reader/dual-write viene usato durante il runtime.
- La PR non installa una nuova ricorrenza ChatGPT né inventa analisi: il runner esistente può invocare il nuovo worker durante la giornata. La Daily conserva tutte le scelte attive in perimetro e tutte le nuove opportunità valide, quindi può ancora avere molte schede senza JD.
- Health reale resta **NEEDS_REVIEW**: 115 fonti PARTIAL, debito e reporting/ricerche da completare; non è stata simulata una certificazione positiva. Validazione tecnica PASS e completamento operativo sono distinti.

## 8. Refactor successivi consigliati

Integrare i packet worker nel runner ricorrente esistente, con conclusioni ChatGPT reali e commit per batch; migliorare i pochi adapter che non espongono location nell'inventory; rivalutare separatamente una futura riduzione delle evidenze semantic storiche, solo dopo aver ridisegnato i guardrail. La soglia London/Luxembourg può essere modificata esplicitamente quando decisa dall'utente.
