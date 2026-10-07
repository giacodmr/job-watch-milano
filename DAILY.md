# Job Watch Daily

Le business rule canoniche restano in `job_watch_rules.json`. La Daily legge soltanto quel file, `daily_worklist.json` e il riepilogo health. Non caricare inventory, memoria integrale, archivio o JD complete nel contesto della chat.

1. Verifica lo snapshot e la data Europe/Rome. Se cambia durante il lavoro, ricarica la worklist prima di inviare aggiornamenti.
2. Mostra le `NEW_INTERESTING`, tutte le scelte `INTERESTED` e `TO_REVIEW` in perimetro, e i `REMINDER`. Per scelte attive chiuse/non verificabili, mostra un breve avviso di lifecycle. Aggiungi una riga coverage/health; il debito semantico resta interno.
3. Le `NEW_CANDIDATE` sono una selezione di massimo 20 vacancy dal nuovo snapshot, non un inventario da mostrare. Recupera la JD ufficiale solo per una vacancy realmente da analizzare. Non salvare il testo. I risultati interessanti diventeranno `NEW_INTERESTING` al sync successivo. Nessun limite alle nuove opportunità valide già valutate.
4. “Già vista” significa effettivamente comunicata in chat. Non marcare come surfaced le vacancy raccolte, analizzate o soltanto presenti nella worklist. I reminder high-fit sono ammessi una volta al giorno, solo nei tre giorni dal primo surfacing noto; non estendere la finestra a ogni reminder. Le variazioni tecniche del fingerprint non bastano a riaprire il reporting. Un cambiamento materiale nei contenuti semanticamente valutati può essere indicato con `material_change: true` nella decisione.
5. `NOT_INTERESTED` sopprime l'identità anche se cambia fingerprint. `APPLIED` conserva la scelta e resta fuori dalla Daily e dalla normale re-review. Non generare APPLIED_UPDATE. Le scelte precedenti non vanno eliminate quando la vacancy chiude.
6. Esegui la ricerca autonoma leggera per batch e registra query, data, fonte e risultato reali. Una scoperta deve entrare nell'inventory ufficiale del batch con ID, URL, fingerprint, `first_seen_at` e summary riconciliati. ATS maintenance/deep discovery restano settimanali.
7. Invia una patch piccola con lo snapshot copiato dalla worklist, quindi esegui `python job_watch.py sync`. Leggi il nuovo health persistito: DAILY_COMPLETE riguarda selezione Daily/reporting/ricerca/copertura; FULL_SEMANTIC_COMPLETE richiede anche debito zero. Non fabbricare evidenze per ottenere COMPLETE.

Le sezioni della patch sono comandi, non nomi di file persistenti. Il sync aggiorna solo le memorie interessate, conserva le sezioni indipendenti e registra ricevute di replay:

```json
{
  "version": "1.0",
  "snapshot": {"run_id": "copia l'intero snapshot della worklist"},
  "semantic_decisions": {"jw3": {"Company::ID": {
    "fingerprint": "...", "analysis_status": "ANALYZED",
    "analysis_method": "chatgpt_semantic_triage", "decision": "REJECT",
    "reason": "WRONG_FUNCTION", "rationale": "Motivo concreto e breve.", "analyzed_at": "..."
  }}},
  "surfaced_jobs": {"jw3": {"Company::OTHER_ID": {
    "fingerprint": "...", "surfaced_at": "...", "surfaced_status": "NEW"
  }}},
  "user_decisions": {"Company::ID": {
    "decision": "NOT_INTERESTED", "fingerprint": "...",
    "reason": "Troppo senior", "rejection_reason": "TOO_SENIOR", "decided_at": "..."
  }},
  "activity": {"JW3": {"searches": [{
    "query": "ricerca realmente eseguita", "checked_at": "...",
    "source_url": "https://fonte-ufficiale.example", "result": "esito verificato"
  }], "discoveries": []}}
}
```

Ometti le sezioni non usate. L'esempio snapshot è abbreviato; copialo integralmente. Per review completa usa i campi di `harden_job_watch_state.REQUIRED_SEMANTIC_FIELDS`, inclusi seniority, esperienza, salary e guardrail L.68/99. Triage non ammesso per priority, seniority o ambiguità L.68/99. Nuove rejection richiedono un motivo esplicito; se vago chiedi il motivo, senza inventarlo.

# Worker indipendenti durante la giornata

Ogni worker riceve soltanto un batch di 1–30 vacancy. La selezione è derivata da current + memory del suo batch, con priorità Amazon/Mastercard, NEW/UPDATED, ruoli plausibili, geography e oldest-first. Non dipende dalla Daily né dai file degli altri batch.

```sh
python semantic_worker.py select jw3 --limit 20
python semantic_worker.py select jw3 --limit 20 --fetch
```

Il primo comando produce metadata e uno snapshot locale al batch; il secondo aggiunge JD temporanee a stdout. Consuma quel packet in memoria nella sessione, senza committarlo o inserirlo nella worklist. I fallimenti fetch restano `jd_error`, non diventano decisioni inventate. Non richiedere `--fetch` quando basta un triage ammesso su metadata. Per i ruoli plausibili/priority usa la JD ufficiale, verificando corrispondenza ID e requisiti.

Il worker restituisce un oggetto `{"batch":"jw3","snapshot":{...},"semantic_decisions":{"Company::ID":{...}}}` e lo applica:

```sh
python semantic_worker.py apply jw3 --patch /tmp/jw3-decisions.json
```

Il commit è atomico, controlla snapshot e guardrail, è replay-safe e modifica soltanto `job_memory_jw3.json`. JW1/JW2/JW4 seguono lo stesso contratto. Rimuovi il packet temporaneo dopo l'uso. Ripeti selezione → analisi → apply fino a coda vuota, poi rigenera la Daily con `python job_watch.py sync`. La PR fornisce i worker eseguibili; la ricorrenza e l'esecuzione ChatGPT sono responsabilità del runner/chat già configurato, non di un finto analizzatore deterministico.
