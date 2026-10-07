# State architecture — daily-first

## Authority e dependency map

| Dato | Prima: writer / reader | Dopo |
|---|---|---|
| Stato ufficiale | collector, reconcile → current → sync/audit | current per batch; first_seen/last_seen e lifecycle ufficiale; CLOSED fuori dal current |
| Review GPT | patch → semantic_decisions → sync | patch/worker → job_memory.semantic → projection/validator |
| Scelte utente | patch → user_job_decisions globale → reconcile/sync | job_memory.user per batch; identità soppressa anche su fingerprint nuovo |
| Mostrato in chat | patch → surfaced_jobs → sync/worklist/audit | job_memory.surfacing; primo/ultimo timestamp, count, fingerprint e firma materiale |
| Analysis | sync → analysis_results, con first_seen e storia unici → worklist/audit/validator | project_batch(current, memory, rules); solo in memoria |
| Pending | sync → semantic_queue → audit/validator | queue derivata; packet worker di 1–30 righe |
| JD | enrichment → semantic_jd_cache → worklist, più testo nello snapshot Amazon | fetch_candidates(..., fetch=True) → stdout temporaneo; scartato dopo review |
| Daily | analysis + cache + surfaced + users | current + memory + rules; metadata, breve conclusione, tasks |
| Storia chiusi | current/analysis hot | archivio JSONL compatto, scritto senza leggerlo; memorie decisionali preservate |
| Geography | regex città, quasi tutte le società London | allowed_locations nella company authority, prima del JD fetch |

La pipeline è `OFFICIAL SOURCES → current_jobs_jw1..jw4 → job_memory_jw1..jw4 → daily_worklist`, con JD just-in-time e archive freddo. Le frecce indicano dipendenze: current e memory sono autorità distinte, non copie della stessa proiezione. Amazon conserva un receipt ufficiale di priority coverage con metadata/hint e fingerprint; i campi JD completi vengono rimossi dopo classificazione/twin linkage e prima della persistenza. La sua overlay è riconciliata in current da sync; la proiezione normale legge soltanto current/memory.

## Invarianti

- Ogni current in perimetro è proiettabile senza analysis file. Pending = open + needs_analysis dopo regole e decisioni; nessuna queue versionata.
- Semantic, user e surfacing sono sezioni indipendenti. Nessun full JD in memoria. I guardrail esperienza/seniority/L.68/salary restano validati.
- APPLIED e NOT_INTERESTED non generano re-review ordinaria. INTERESTED/TO_REVIEW restano visibili in perimetro, inclusa una nota di lifecycle quando necessario.
- Nessun modello/config version invalida automaticamente decisioni valide. Fingerprint e contesto del modello/regole sono distinti.
- Surfacing richiede effettivo output in chat. Reminders high-fit, una volta al giorno e prima di 72 ore dal primo surfacing noto. Titolo/location/famiglia e flag semantico materiale distinguono materiale da variazioni tecniche.
- La selezione Daily è bounded su uno snapshot ufficiale: decidere una riga non assegna nuovo debito. I worker selezionano invece i pending rimanenti fino a zero.
- Il worker di un batch legge soltanto current/memory/ATS mapping del batch e configurazione condivisa, e scrive soltanto la sua memoria. Lock e journal proteggono commit, replay e append dell'archivio.
- CLOSED vengono archiviati e rimossi dal current. Archivio mai letto da runtime quotidiano. Le memorie pregresse restano conservate per deduplica e scelte.
- Migrazione verificata prima della rimozione dei 21 file legacy. Decisioni non attribuibili a un batch sono preservate nel receipt, senza silent drop.

## Compromessi deliberati

La memoria semantica conserva i campi di evidenza già richiesti dai guardrail, anche per review storiche e chiuse. Non tronchiamo retroattivamente queste evidenze per ottenere un file artificiosamente piccolo. ChatGPT riceve soltanto packet piccoli e rationale abbreviata nella Daily; non deve leggere l'intera memoria.

I registri surfaced precedenti conservavano spesso un solo timestamp, talvolta senza fingerprint. L'upgrade conserva esattamente quel dato e usa quel timestamp come primo/ultimo noto e count 1 se manca un conteggio. Non può ricostruire messaggi chat mancanti; questi conteggi sono limiti inferiori, non storia inventata.

I siti che nascondono la location nell'inventory richiedono ancora una pagina di dettaglio per localizzarla. Non vengono avviati ulteriori fetch JD o review dopo un'esclusione geography. Gli inventory globali inevitabili vengono filtrati appena è disponibile la location.

Il modulo d'upgrade è mantenuto per restore/rebase ripetibili e test di migrazione, senza dual-write né fallback readers runtime. Una ricorrenza GPT deve invocare il worker e produrre conclusioni reali; il codice non simula analisi ChatGPT. Nessuna nuova automazione viene installata dalla PR.

Vedi `STATE_REFACTOR_REPORT.md` e il receipt `state_migration_report.json` per misure e validazione sullo snapshot migrato.
