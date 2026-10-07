# JobWatch Daily

Le regole permanenti sono in `job_watch_rules.json`. Questo file descrive soltanto l'esecuzione.

1. Leggi `daily_worklist.json`, `job_watch_healthcheck.json` e le regole. Verifica data Europe/Rome, `run_id`, timestamp delle quattro fonti, snapshot Amazon e hash delle regole. Se la raccolta è vecchia/in corso o lo snapshot cambia, aspetta il collector/recovery e ricarica il worklist. Non certificare una lettura obsoleta.
2. Processa prima tutte le righe con `needs_semantic_review=true` e `action` diversa da `HISTORICAL_BACKLOG`. Le altre riusano la decisione: non riaprire la JD. Usa `jd` solo se associata allo stesso fingerprint; recupera la JD ufficiale se manca. Triage breve soltanto nei casi ammessi; review completa per plausibili/ambigui, priority e seniority/L.68/99. Registra errori reali senza inventare decisioni.
3. Mantieni TO_REVIEW/INTERESTED visibili, APPLIED fuori dall'apply-now, NOT_INTERESTED persistente sul fingerprint. Mostra nuove opportunità, aggiornamenti materiali, novità Amazon/Mastercard e hidden gems; non ripetere inventari immutati. Persisti `surfaced_at`, `surfaced_status` e **fingerprint** solo per ciò che hai realmente riportato.
4. Fai una ricerca autonoma leggera con evidenza per batch, anche se non produce risultati. Usa aggregatori solo per discovery, conferma su fonti ufficiali. Eventuali nuove vacancy devono entrare nei `current_jobs_<batch>.json` con ID/URL ufficiali, fingerprint e summary riconciliati prima del sync: non aumentare soltanto i contatori. La manutenzione ATS, deep discovery e promozione/pruning di `company_candidates.json` sono settimanali.
5. Dopo il delta, processa la tranche `HISTORICAL_BACKLOG` se resta capacità. Non è un requisito per DAILY_COMPLETE e non allargare la tranche durante lo stesso snapshot. Nessun limite alle nuove opportunità valide.
6. Accumula gli aggiornamenti in **un solo** `daily_updates.json` usando il formato sotto. Il workflow sync li valida/unisce ai registri esistenti e rimuove il patch consumato. In locale: `python job_watch.py sync`. Prima della scrittura confronta nuovamente lo snapshot con quello corrente.
7. Registra in `activity` le ricerche realmente eseguite, con `query`, `checked_at`, `source_url`, `result` e `discoveries` (chiavi ufficiali presenti negli snapshot, lista vuota se nessuna scoperta). Il sync unisce queste evidenze in `daily_activity.json`. `job_watch_run_state.json` è derivato: non scrivere flag di completamento o timestamp copiati. Priority è VERIFIED/PARTIAL/FAILED/NOT_RUN, derivata dalla raccolta ufficiale; JW3/JW4 non richiedono una priority inventata.
8. Attendi il workflow sync; verifica la conclusione Actions e il **nuovo healthcheck persistito**, stesso run_id. `DAILY_COMPLETE` e `FULL_SEMANTIC_COMPLETE` sono distinti. Il health elenca `remaining_work` quando manca lavoro effettivo. Errori locali/source e copertura PARTIAL possono produrre COMPLETE_WITH_WARNINGS; una vacancy non verificabile resta UNKNOWN con la scelta utente preservata e un warning di manutenzione. GLOBAL_FATAL_ERROR impedisce la certificazione di tutto il run.

Non caricare inventari, analysis results o cache integrali per il normale lavoro semantico. Quando serve una correzione specifica, leggi soltanto il relativo file/record. Non eliminare chiavi storiche né trasformare rejection reasons in hard rules.

## Patch piccolo

Copia `snapshot` esattamente dal worklist. Le sezioni non modificate si possono omettere. Le chiavi batch sono minuscole.

```json
{
  "version": "1.0",
  "snapshot": {"run_id": "...", "source_generated_at": {}, "priority_snapshot_at": {}, "rules_sha256": "...", "source_sha256": {}},
  "semantic_decisions": {"jw1": {"Company::ID": {"fingerprint": "...", "analysis_status": "ANALYZED", "analysis_method": "chatgpt_semantic_triage", "decision": "REJECT", "reason": "WRONG_FUNCTION", "rationale": "Motivo concreto", "analyzed_at": "..."}}},
  "surfaced_jobs": {"jw1": {"Company::ID": {"fingerprint": "...", "surfaced_at": "...", "surfaced_status": "NEW"}}},
  "user_decisions": {"Company::ID": {"decision": "NOT_INTERESTED", "fingerprint": "...", "reason": "Troppo senior", "rejection_reason": "TOO_SENIOR", "decided_at": "..."}},
  "activity": {"JW1": {"searches": [{"query": "Ricerca realmente eseguita", "checked_at": "...", "source_url": "https://fonte-ufficiale.example", "result": "Esito verificato"}], "discoveries": []}}
}
```

L'esempio illustra sezioni indipendenti; una vacancy scartata non va aggiunta a surfaced_jobs. Per review completa usa i campi già prescritti in `job_watch_rules.json`/`harden_job_watch_state.py`. Il codice accetta soltanto semantic/surfaced patch riferiti a righe presenti nel worklist e allo stesso fingerprint. Le registrazioni utente conservano tutti i record precedenti.

Per un nuovo NOT_INTERESTED con motivo chiaro, il sync inferisce la categoria quando manca. Se l'utente dice soltanto «scarta», «no», «togli», «non mi interessa», chiedi il motivo prima di persistere, con opzioni cliccabili se supportate. Fallback: seniority · salary · funzione · sede · determinato · sales · tecnico · dominio · altro. Non inventare motivi storici mancanti.

`job_watch_summary.txt` contiene il riepilogo immediato, pubblicato anche nella pagina Actions. Una patch con snapshot cambiato viene conservata per reload/re-review e non scrive registri; una riga invalida viene isolata in `rejected_daily_updates.json` mentre le altre righe valide sono salvate. Il lock serializza processi locali; le scritture dei registri usano un journal recuperabile. Non scrivere JSON derivati a mano.

Ogni patch consumata ha una ricevuta (`applied_update_ids` in `daily_activity.json`). Il replay da un checkout Actions vecchio è un no-op: non può sovrascrivere decisioni/evidenze più recenti. Le righe rifiutate richiedono una patch corretta, non il replay della vecchia.
