# Audit scheduler Job Watch — 9 ottobre 2026

## Esito e limite della diagnosi

Il difetto osservato è **assenza della workflow run `event=schedule`**. Non è
una run in coda, un job skipped o un errore del Collector. La causa interna
della mancata creazione non è esposta dalle API GitHub consultate: ritardo,
evento scartato e registrazione interna difettosa restano possibilità non
distinguibili senza verifica GitHub. Non è provata una restrizione dell'account.

I due bug di recovery corretti sotto non spiegano l'assenza della run: si
manifestano soltanto dopo che un evento ha già avviato il workflow.

Repository ID: `1353778491`; workflow ID: `358220754`.
Default branch: `main`; repository pubblico, non fork, non archiviato.

## Cronologia verificata

Gli orari di questa tabella sono Europe/Rome (UTC+02:00 alle date indicate).

| Commit | Data e ora | Cron presente dopo il commit |
| --- | --- | --- |
| `495640c` | 7 ottobre 19:25:56 | 23:00, 23:45 Rome |
| `184c926` | 8 ottobre 00:48:06 | 21:12, 21:42, 22:12, 22:42 UTC |
| `075f7a6` | 8 ottobre 00:55:00 | 23:00, 23:45 Rome più gli slot UTC precedenti |
| `d8e106f` | 8 ottobre 23:06:53 | 23:07, 23:17, 23:32, 23:47 Rome |
| `5420a96` | 8 ottobre 23:55:18 | Quattro slot production più un solo cron temporaneo per il test |

Il primo slot delle 23:07 aveva appena sette secondi di margine. Questo
impedisce di usarlo come prova attendibile della propagazione del nuovo cron;
non dimostra che la propagazione sia la causa degli altri slot mancanti.

Il ritardo precedeva questi cambiamenti:

| Run scheduled | Creazione UTC | Schedule nel commit della run |
| --- | --- | --- |
| [36965811044](https://github.com/giacodmr/job-watch-milano/actions/runs/36965811044) | 2 ottobre 04:43:42 | 06:30 Rome; ritardo 13m42s |
| [37114851222](https://github.com/giacodmr/job-watch-milano/actions/runs/37114851222) | 3 ottobre 09:58:50 | 06:30, 07:15, 08:00 Rome |
| [37456355955](https://github.com/giacodmr/job-watch-milano/actions/runs/37456355955) | 6 ottobre 11:25:58 | 06:30, 07:15 Rome |
| [37612906878](https://github.com/giacodmr/job-watch-milano/actions/runs/37612906878) | 7 ottobre 11:15:55 | 06:30, 07:15 Rome |
| [37616482330](https://github.com/giacodmr/job-watch-milano/actions/runs/37616482330) | 7 ottobre 11:47:29 | 06:30, 07:15 Rome |

Per gli eventi con più slot non è stato registrato il cron del payload nei
vecchi log: non è possibile attribuire una run a uno specifico slot. Le run
del 7 ottobre hanno `created_at = run_started_at`; le ore trascorse non sono
attesa del runner dopo la creazione. La run `37460397239` letta come attempt 2
mostrava un avvio il giorno dopo: l'API dell'attempt 1 conferma invece creazione
e avvio il 6 ottobre alle 12:02:01 UTC, conclusione 12:02:17. Non era una coda
di diciotto ore.

## Controlli della configurazione reale

- API workflow: `active` prima e dopo il test di riattivazione.
- UI Settings → Actions → General: `Allow all actions and reusable workflows`.
- UI Actions → Policies: nessuna policy creata. Policy insights richiede
  Enterprise e non fornisce log utilizzabili su questo account.
- Actor delle ultime schedule e autore/committer dell'ultimo cron: `giacodmr`.
  Repository personale; nessuna evidenza di deprovisioning Enterprise Managed User.
- Nessuna run `requested`, `queued`, `pending`, `waiting` o `in_progress`
  residua nei controlli finali precedenti allo slot conclusivo del test.
- CI e manual dispatch accettano il workflow. Le annotazioni controllate
  contengono un notice sulla futura migrazione Ubuntu, non errori YAML.
- I commit automatici di stato non cambiano il cron e non toccano i sentinel
  che avviano il Collector. Il test di Sync non ha modificato gli inventari.
- L'altro repository pubblico dell'account non contiene workflow: manca un
  controllo indipendente già esistente per isolare una causa a livello account.
- GitHub Status risultava operativo; questo non prova che ogni cron sia stato
  consegnato né collega il nostro caso a un incidente pubblicato.

## Correzioni applicate e prove

1. `d881523`: checkout esplicito di `main` dopo l'acquisizione della concurrency,
   nel freshness guard e nel Collector. Una run accodata conserva il proprio
   event SHA, che potrebbe precedere la raccolta pubblicata dal writer precedente.
   Aggiunti log event/cron/event SHA/state SHA/decisione e timeout del guard.
   Il test `test_scheduler_recovery.py` esegue il vero script YAML contro un
   repository Git con event SHA stale e `main` fresco: due tentativi no-op,
   giornata incompleta da recuperare e manual dispatch forzato.
2. `009e8f8`: checkpoint finale dello snapshot dopo la maintenance del Collector.
   La maintenance poteva aggiungere metadati agli inventari dopo il checkpoint,
   lasciando hash incoerenti e causando recovery non necessarie. Il nuovo test
   attraversa quella maintenance e verifica hash, readiness e Sync successivo.
3. `477144d`: preflight Worker riconosce anche `requested/pending/waiting`.
   Il test live ha dimostrato che la coda condivisa usa davvero `pending`;
   il vecchio testo controllava soltanto `queued/in_progress`. Correzione
   applicata anche al prompt della task ChatGPT esistente, salvata e riletta
   dopo reload. Allineati i riferimenti documentali agli orari production.

4. Push dei sentinel trattati come recovery idempotenti: anche dopo un push,
   il guard rilegge lo stato corrente prima di raccogliere. Solo
   `workflow_dispatch` forza la raccolta. Una nuova asserzione sul vero script
   YAML falliva prima della modifica (`should_run=true` su snapshot completo)
   e passa dopo: push completo no-op, push incompleto recovery. Questo copre
   anche il recupero del Worker se una raccolta termina mentre il push attende.

| Prova | Evento | Timestamp UTC | Esito |
| --- | --- | --- | --- |
| [37850100710](https://github.com/giacodmr/job-watch-milano/actions/runs/37850100710) | push, CI | 8 ottobre 21:55:25–21:56:03 | 143 test PASS, validazioni PASS |
| [37850165830](https://github.com/giacodmr/job-watch-milano/actions/runs/37850165830) | workflow_dispatch, Collector | 8 ottobre 21:56:00–22:04:40 | success; Collector terminato 22:04:39 |
| [37850360154](https://github.com/giacodmr/job-watch-milano/actions/runs/37850360154) | workflow_dispatch, Sync | richiesta 21:57:44; job 22:04:42–22:05:02 | pending durante Collector, poi success |

Il Sync è iniziato tre secondi dopo la fine del Collector: nessuna
sovrapposizione fra writer. Diff del commit Sync: solo health/pipeline,
zero modifiche a `current_jobs`, memory e archive. Readiness finale vera,
`recovery_needed` falso, nessuna chiave vacancy duplicata. Le scelte semantiche
e gli update ID preesistenti sono preservati; aggiornati i normali last-seen e
aggiunte due chiusure all'archivio senza riscriverne lo storico.

## Test reale del trigger

Cron temporaneo: `12,27,42,57 0 9 10 *`, timezone `Europe/Rome`.
Commit 8 ottobre 21:55:18 UTC. Slot attesi UTC: 22:12, 22:27, 22:42, 22:57.
Margini dal commit: 16m42s, 31m42s, 46m42s, 61m42s.

Alle 22:44 UTC non risultavano nuove run schedule; l'ultima era ancora
`37616482330` del 7 ottobre. Workflow disabilitato e immediatamente riabilitato
una sola volta: API `active`, `updated_at=2026-10-08T22:44:13Z`. Questa operazione
è un esperimento, non una riparazione dimostrata del scheduler interno.

Ultima lettura API del test: 8 ottobre 22:57:12 UTC, nessuna nuova run scheduled
(totale storico 28, ultima del 7 ottobre). Il primo slot aveva superato 45 minuti
senza una run visibile; l’ultimo era appena trascorso, quindi non è una prova
che i suoi eventuali eventi ritardati sarebbero stati definitivamente scartati.
La latenza di registrazione non è quantificabile senza un evento osservato.

Il cron temporaneo è rimosso nel commit che contiene questo report. Restano
soltanto `7 23 * * *`, `17 23 * * *`, `32 23 * * *`, `47 23 * * *`, tutti con
`Europe/Rome`; `queue: max` e manual dispatch preservati. Lo stesso commit
aggiorna `.job_watch_run` per il test live del push su snapshot già completo.
Il risultato di quella run è riportato nel resoconto finale della sessione.

## Ricerca online e soluzione operativa

[GitHub documenta ritardi e possibili scarti](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
[Timezone è supportato dal 19 marzo 2026](https://github.blog/changelog/2026-03-19-github-actions-late-march-2026-updates/).
[Queue max è documentato](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
[Le execution protections possono filtrare gli eventi prima della run](https://github.blog/changelog/2026-09-17-workflow-execution-protections-in-github-actions-generally-available/),
ma qui non risultano policy personalizzate.

Report originali del [2 ottobre](https://github.com/orgs/community/discussions/209332)
e [4 ottobre](https://github.com/orgs/community/discussions/209473) descrivono
lo stesso sintomo su altri account, anche con workflow minimi. Non sono una
diagnosi ufficiale del nostro repository. Non è supportata l'affermazione
che si tratti necessariamente di uno “shadowban”.

Il recupero indipendente già esistente è la task ChatGPT `Job Watch Worker`:
legge `worker_snapshot_ready`, evita Collector non conclusi e, soltanto quando
necessario, aggiorna `.job_watch_run` per provocare un evento `push`. Poi termina;
lo slot successivo riparte dallo stato remoto. Task verificata attiva nella UI,
con preflight corretta persistita. Nessun servizio aggiuntivo necessario per
mantenere questa strategia. La riuscita dei test manuali non certifica però
un futuro avvio automatico ChatGPT o una futura scrittura autorizzata della task.

## Richiesta tecnica pronta per GitHub Support

Repository `giacodmr/job-watch-milano` (ID `1353778491`), workflow
`.github/workflows/collect_jobs.yml` (ID `358220754`), default `main`, active.
Please inspect server-side cron registration, scheduled-event delivery and any
account/repository schedule restrictions for the missing October 8/9 events.
Manual run `37850165830` succeeded; queued Sync `37850360154` also succeeded.
Latest observed schedule was `37616482330`, created October 7 11:47:29 UTC.
The workflow uses officially supported IANA timezone and queue max syntax.
Repository Actions are enabled and no custom execution policies exist.
The test cron commit, expected slots and controlled disable/enable timestamp
are listed above. We need the internal reason for missing run creation,
not diagnosis of a failed or runner-queued job. This request has not been sent.
