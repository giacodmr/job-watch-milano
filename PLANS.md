# Job Watch Web App — piano incrementale

## Fase 0: fondamenta

Audit di `main` a `0f6287a461de3951ba6dc4d2a00235a5fde494fd` (2026-10-29). Risultati e rischi in `apps/web/docs/AUDIT.md`. Nuova applicazione isolata, schema D1 versionato, health locale, contratti, test e CI dedicata. Nessun import operativo, comando remoto, autenticazione remota attiva o deploy.

Addendum audit e riallineamento al main `6725fefa45e5bab0494ceb05b9edb2fe999a1e1f` completati prima della consegna; PR #23 per la revisione delle fondazioni.

Criteri: build strict, test API e SQL su D1 locale, doppia applicazione migrazioni, bundle Worker verificato senza upload; nessuna modifica ai file produttivi preesistenti. Consultare `apps/web/docs/VALIDATION.md` per l'esito effettivo.

## Fase 1: sincronizzazione di sola lettura, locale — implementata

Incarico eseguito: «Implementa in `apps/web/` un exporter/importer di sola lettura da un checkout Git fissato a uno SHA esplicito verso D1 locale, secondo SYNC_CONTRACT v1. Usa allowlist, decodifica verificata delle evidenze, archivio e alias Python esistenti. Non accedere al cloud, non modificare il Job Watch e non abilitare comandi. Aggiungi un Vacancy Explorer minimo, paginato e una vista provenienza/freschezza».

Criteri di completamento:

- Input da checkout detached/coerente; manifest completo con file hash, conteggi e chunk; mai JD integrali o contenuti sensibili nel prodotto/log.
- Unione inventari + identità delle memorie + archivio, con provenienza e date. Non dedurre CLOSED dalla sola assenza o da copertura parziale. Separare stato sconosciuto, scarto automatico e decisione utente.
- Riesecuzione identica senza duplicati; stesso chunk con hash diverso rifiutato; crash durante import mantiene visibile lo snapshot precedente; finalizzazione atomica di checkpoint e audit; conflitto su revisione impedisce regressione.
- Fixture per Amazon ID alias, decisioni cross-fingerprint, memory evidence pool, chiusure, sorgenti parziali, snapshot incoerenti e revisioni precedenti.
- UI legge esclusivamente l'ultimo checkpoint confermato; filtri paginati tramite indici. Stato di freschezza esplicito, nessun falso zero in caso di errore.
- Misura righe lette/scritte, byte e CPU; definisce budget sotto i limiti Free. Nessun fetch JD e nessuna chiamata ChatGPT/API LLM.

Esito Fase 1: exporter isolato da Git, manifest/hash verificati, D1 locale con chunk riprendibili e checkpoint CAS atomico, servizi dati indipendenti da HTTP per futuro MCP, Explorer paginato con filtri/history/provenienza. Dettagli e misure in `apps/web/docs/PHASE1_VALIDATION.md`; base 84593e9 e main ricontrollato 3661d7a. Tre skill UI applicate e browser desktop/mobile verificato. Nessun comando operativo o accesso remoto.

Limiti espliciti: CPU misurata soltanto come processo/figli locali; CPU Worker remoto non verificata. Bootstrap 113.175 scritture, sopra il Free giornaliero: default 70.000 per invocazione e ripresa chunk, override solo locale. Deduplica di versioni invariate, retention e budget aggregato account/giorno sono gate obbligatori prima di sync cloud continuativa. Il bulk import attuale non gira in una richiesta Worker. Nessun MCP server è stato costruito.

## Fase 2: accesso privato e ambiente remoto, previa autorizzazione

Configurare Cloudflare Free/D1/Access solo dopo autorizzazione. Validare JWT e policy allowlist per identità interattiva, service token con policy Service Auth per ingestion. Nessun servizio autorizzato ai comandi utente. Testare accesso negato su tutti gli host, URL di preview e asset. GitHub App server-side con privilegi minimi, nessun token frontend. Verificare budget account GitHub e stop a spesa zero; import remoto inizialmente read-only e canary con rollback checkpoint.

Criteri: test crittografici JWT, audience errata/scaduta, separazione ruoli, CSRF same-origin per future mutation, chiavi ruotate, account Free verificato, percorsi alternativi non raggiungibili, restore documentato. Nessuna spesa aggiuntiva o pubblicazione non autorizzata.

## Fase 3: comandi confermati e decisioni utente

Prima progettare un adapter produttivo in PR separata: il bridge attuale accetta solo select/apply semantico; non è un endpoint generico per aziende o decisioni utente. Conservare controlli Python, lock/concurrency condivisa, snapshot e receipt; partial apply gestito per record. Persistenza comando e audit nella stessa transazione, retry finiti con revisione e riconciliazione dopo esito incerto. Nessuna conferma anticipata.

Criteri: duplicate click, request-ID collision, conflitto fingerprint, scelta utente concorrente, push riuscito con risposta persa e sync di conferma coperti da test. `CONFIRMED` solo dopo verifica risultato remoto, commit antenato del checkpoint e corrispondenza dei valori proiettati. Nessun cambiamento alle regole.

## Fase 4: coda ChatGPT e monitor

Separare «richiesta analisi registrata», «packet pronto», «review applicata» e «confermata». Per una vacancy arbitraria serve estensione esplicita del worker/bridge; fino ad allora `BLOCKED_UNSUPPORTED`. Context verso ChatGPT solo con azione utente, metadati minimi e URL; nessun segreto/JD nella query URL. Pipeline Monitor con retry tecnico attuale rispettato, KPI derivati da snapshot confermati.

## Fasi successive, fuori ambito

Gestione aziende/tier/fonti solo mediante comandi validati e autorità attuali. Application tracker e MCP dedicato richiedono ADR e incarico distinti. Nessun nuovo broker, cron o database finché il caso d'uso non lo giustifica.

## Consolidamento tecnico della base D1

PR #25 aggiornata sul proprio branch, riallineata a main 0b2984a. Schema 5 additivo, fix di cursor Unicode/ricerca lunga/nome azienda versionato e misure separate reali. Esiti e gate: `apps/web/docs/PHASE1_CONSOLIDATION.md`. GO solo locale/read-only dopo CI sul relativo head; nessun cloud o merge automatico. Non integrare #29; preservare dalla #30 soltanto servizi e comportamenti dati, tramite hunk dopo #25. V7 resta una PR successiva. Prossimo intervento consigliato: fast path locale per commit con file allowlist identici, senza duplicare versioni/appartenenze né perdere provenance/history.

## Modello C / PR 1 — contratti e prove

#25 integrata tramite squash 004782c1d5b53c9c6abb0399c8368f28831104c7. Branch dedicata da main: contratti puri di selezione/ledger, protezione decisioni e digest dati+codice, checker read-only e prove sintetiche/private aggregate. Nessuno schema/importer/reader nuovo. Criteri, limiti e gate PR 2 in apps/web/docs/MODEL_C_SELECTION_CONTRACT.md.
