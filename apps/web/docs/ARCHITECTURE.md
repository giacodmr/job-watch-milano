# Responsabilità e flussi

## Confine attuale

La Fase 0 esegue soltanto browser locale → Worker locale → lettura versione schema D1 locale → health. UI e API sono compilate separatamente; condividono contratti validati senza accesso a secret o moduli Python. Nessun exporter, dispatcher, cron o sincronizzatore è attivo.

```mermaid
flowchart LR
  B[Browser locale React] -->|GET /api/health| W[Worker locale]
  W -->|SELECT versione schema| L[(D1 locale)]
  B -.->|POST comandi: 501| W
  G[Job Watch Python e Actions] --> R[GitHub main operativo]
```

## Target V1, ancora da implementare

```mermaid
flowchart TD
  U[Utente] --> A[Cloudflare Access: login interattivo]
  A --> UI[React privata]
  UI --> API[Worker API: JWT verificato e autorizzazioni]
  API -->|consultazione checkpoint confermato| D[(D1: proiezioni persistenti)]
  API -->|comando validato e audit atomici| C[(D1 commands)]
  C --> AD[Adapter server: permessi GitHub minimi]
  AD -->|richiesta idempotente futura| GH[GitHub Actions: writer serializzato]
  GH --> PY[Job Watch Python e regole attuali]
  PY --> R[GitHub: commit e receipt verificati]
  R --> EX[Exporter allowlist da commit fissato]
  EX --> SA[Access Service Auth: solo ingestion]
  SA --> IN[Importer Worker: staging chunk e controllo versione]
  IN -->|conferma atomica checkpoint e audit| D
  D -->|risultato effettivo riconciliato| C
  GH --> PK[Packet JD temporaneo autorizzato]
  PK --> CHAT[ChatGPT Chat: worker esterno]
  CHAT -->|review via strumenti GitHub autorizzati| AD
```

Le frecce future non dichiarano capacità già disponibili: l'adapter mutativo e la selezione arbitraria non esistono ancora. ChatGPT non è invocato dall'app tramite API; il browser può in futuro aprire un contesto esplicito con metadati minimi e URL, mai JD o credenziali nei query parameter.

## Distribuzione delle responsabilità

- GitHub/Python: unica autorità V1 per regole, configurazione, ciclo di vita, decisioni, fingerprint, alias, certificazione e azioni operative.
- D1: livello di consultazione durevole e storico delle versioni osservate, più intenti dei comandi e audit. Non sovrascrive lo stato operativo prima dell'ACK. Le review semantiche e le decisioni utente hanno tabelle diverse.
- Worker: verifica identità, autorizzazione, validazione, limiti di input, accesso D1 indicizzato e adapter GitHub server-only. In Fase 0 solo health, con runtime remoto bloccato.
- Frontend: mostra freschezza/provenienza/stato tecnico, raccoglie intenzioni, non decide regole o completamento. Nessun accesso GitHub diretto o segreto.
- Importer futuro: allowlist per file e campi; codec memoria verificato; snapshot versionati e checkpoint CAS. L'import di file non equivale a pubblicazione.
- CI nuova: verifica esclusivamente nuova app e schema locale, read-only, senza secret, artifact o cloud.

## Schema e consistenza

`companies`, `sources`, `jobs` sono identità durevoli. `company_versions`, `source_versions`, `job_versions` portano metadati e provenienza per snapshot: un import parziale non sovrascrive i dati visibili. I riferimenti alle identità non vengono cancellati quando le vacancy chiudono. `job_aliases` conserva chiavi legacy confermate senza fondere aziende diverse.

`sync_snapshots` e `sync_chunks` registrano staging, integrità e completamento dei chunk. `sync_checkpoints` contiene la revisione attiva: solo snapshot confermati. Letture future partono dal checkpoint e filtrano tutte le versioni per quell'ID; mai `max(timestamp)` su dati in staging. I dati identità da staging non sono consultabili senza join al checkpoint.

`semantic_reviews` e `user_decisions` sono eventi deduplicati per hash del risultato decodificato; la review è legata al fingerprint, la scelta utente all'identità. Letture eventi filtrano snapshot d'origine confermati e ordinano timestamp/precedenza Python. Il risultato effettivo va portato dall'exporter, non ricalcolato nel browser. Le tabelle non contengono JSON libero o JD. I riepiloghi a 360 caratteri non sono una copia completa della review: hash e path consentono verifica nell'autorità GitHub.

`pipeline_runs` distingue ID GitHub, attempt, run hash di pipeline e flag di completamento. `commands` memorizza intenti immutabili e stato del trasporto; `audit_log` è append-only con riferimenti e codici, senza payload. Il database è un supporto, non un confine completo di sicurezza: importer e adapter devono ancora validare autorizzazione, hash, antenati Git e corrispondenza dei risultati prima di finalizzare.

UTC in SQL/API; calendario di retry esistente Europe/Rome conservato come policy Python. Niente cancellazioni a cascata delle identità o dei registri storici. Indici per snapshot/batch/stato/azienda, history per job e coda comandi. Application tracker e MCP richiederanno migrazioni successive.
