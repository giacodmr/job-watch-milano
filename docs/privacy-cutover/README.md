# PR 1 — Safety e preparazione del cutover privacy

Questa PR aggiunge strumenti locali, test sintetici e istruzioni operative per una **futura** conversione in privato di `giacodmr/job-watch-milano`. Nessun comando dello strumento cambia visibilità, esegue dispatch, aggiorna riferimenti remoti, pubblica artifact, avvia collector o accede ai database. Il codice e i workflow produttivi, PR #25 e il design Electric restano fuori dal diff.

## Installazione separata

Python >=3.12, Git completo, `age` e `age-keygen` sono necessari. Usare una virtualenv **esterna al repository** e `pip install -r requirements-privacy-safety.txt`. La produzione continua a usare il proprio requirements invariato; Node e dipendenze web non cambiano. Installare age da una distribuzione ufficiale verificata: <https://github.com/FiloSottile/age/releases>. Non accettare un download non verificato. `--age /percorso/age` o `JOB_WATCH_AGE_BIN` permettono un'installazione locale senza modificare PATH.

`python tools/privacy_cutover.py --help` descrive i comandi. `--root` e `--age` precedono il sottocomando.

- `preflight --phase before|after [--online] [--out FILE] [--baseline FILE]`: dipendenze, documenti, contratti YAML effettivi e metadati GitHub GET-only. Nessuna lettura di log o contenuto artifact. Token solo da `GH_TOKEN`/`GITHUB_TOKEN`, mai come argomento. Nessun redirect autenticato. La CLI non trova né estrae credenziali da altri strumenti.
- `backup --recipient AGE_PUBLIC_RECIPIENT --out FILE`: censimento remoto, mirror completo, `fsck`, bundle autosufficiente e cifratura age. Un cambiamento dei riferimenti durante la cattura interrompe il backup. Nessun archivio in chiaro viene scritto nella destinazione.
- `verify --capsule FILE --identity KEYFILE --sha256 TRUSTED_DIGEST`: decifratura e ripristino completo temporaneo, senza rete durante il restore.
- `restore ... --target NEW_BARE_DIRECTORY`: stessa verifica, poi copia in un nuovo repository bare privato, senza origin, push, checkout o hook. Mai sostituire una directory esistente.
- `continuity --commit FULL_SHA --out FILE [--at ISO_TIME] [--baseline FILE]`: esegue soltanto le proiezioni pure del motore archiviato a quel commit. Copia isolata, ambiente senza credenziali, socket e subprocess disabilitati nel probe, nessuna esecuzione di collect/sync/project CLI. Verifica che i file estratti non cambino. Confronta digest di snapshot, memorie, code, proiezioni e worklist Daily, oltre alla readiness del worker. Non ricostruisce identità o deduplicazione con nuove regole.
- `publish-check --base FULL_SHA`: allowlist dei file di questa PR, blocco binari/symlink e alcuni formati di chiavi/token. È un controllo di contenimento; **non è un rilevatore generale di dati personali** e richiede revisione del diff.

## Evidenze e limiti deliberati

Output pubblicabile: soli codici, stati, conteggi e digest; nessun record, motivo personale, URL di candidatura o payload. I file di evidenza richiedono directory 0700 fuori da **qualsiasi** repository Git, file 0600, nessuna sovrascrittura o symlink. I backup e i checkpoint sono ignorati anche come difesa aggiuntiva, ma `.gitignore` non autorizza a tenerli nel checkout.

Exit code: 0 operazione verificata; 1 errore redatto/fail closed; **2 preflight con gate non chiusi**. `automated_checks_pass` riguarda solo i controlli automatici; `ready` rimane falso in presenza di `MANUAL_REQUIRED`. Il software non autoapprova la custodia delle chiavi, il budget o una ricorrenza esterna. Un mancato confronto non viene salvato come evidenza positiva.

Il backup copre tutti i riferimenti **pubblicizzati al client autenticato** e HEAD, commit/alberi/blob raggiungibili, tag annotati e riferimenti PR pubblicizzati. Confronta l'intero inventario degli oggetti e i riferimenti dopo il restore. Non è una copia di oggetti eliminati/non pubblicizzati dal server, reflog remoto, copie di terzi o metadati del servizio GitHub. LFS, submodule (anche storici), clone shallow/partial e alternates causano un rifiuto esplicito, non un backup dichiarato completo. Limite capsula 2 GiB; superarlo richiede una modifica dello strumento, non un bypass.

La storia originale può già contenere dati personali o descrizioni: conservarne la storia integrale richiede che il **solo backup cifrato privato** li contenga. Non estrarli in documenti, fixture, nuovi commit o D1. Non vengono aggiunte nuove JD. Il manifest dettagliato è dentro la capsula cifrata. age protegge l'integrità del ciphertext ma non autentica autonomamente il mittente: conservare il digest SHA-256 fidato su un canale separato, insieme al registro privato della prova. La chiave privata deve restare separata dal backup.

Il probe è una misura contro accessi accidentali del codice fidato del motore, non una sandbox contro codice ostile. Il plaintext temporaneo vive solo in directory 0700 e viene rimosso normalmente; un arresto forzato può lasciare residui. Usare un disco locale cifrato e verificare la pulizia, senza promettere cancellazione fisica su SSD.

Le impostazioni GitHub, ricorrenze ChatGPT, autorizzazioni App, secret, variabili, issue, commenti, release, log, artifact e wiki non sono contenuti nel bundle. Registrare privatamente configurazioni e metadati necessari; i valori dei secret non sono recuperabili dalle API GitHub e richiedono custodia/re-emissione separata. Non scaricare o allegare artifact/log indiscriminatamente.

Vedere [runbook](RUNBOOK.md) e [verifiche effettive/handoff](VALIDATION.md). I servizi dati, i due futuri D1, `USER_DISMISSED`, le migrazioni e il redesign appartengono alle PR successive.
