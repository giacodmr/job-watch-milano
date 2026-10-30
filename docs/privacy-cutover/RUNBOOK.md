# Runbook futuro — conversione e recupero

**Documento operativo; nessuna conversione è stata eseguita da questa PR.** La sola approvazione della PR non autorizza il cutover. Operatore: proprietario del repository, con accesso admin, chiave di recupero privata e controllo delle ricorrenze ChatGPT. Non eseguire i passi di scrittura senza un incarico successivo esplicito.

## 1. Gate prima della finestra

1. Confermare in GitHub identità del repository e default branch main. Mantenere lo stesso repository: niente copia sostitutiva, history rewrite, force push, reset dei dati o rigenerazione degli identificativi. Annotare privatamente stato e head della PR #25 e delle altre PR aperte.
2. Verificare billing effettivo del proprietario, allowance Actions già consumata **condivisa con gli altri repository**, storage artifact/cache e blocco dell'utilizzo a pagamento. Usare runner standard Linux. Non presumere che un budget con solo alert o un budget non applicabile blocchi gli addebiti. Se lo zero costo non è dimostrato, STOP; nessun upgrade o servizio aggiuntivo.
3. Verificare le funzionalità che si perdono passando a privato su GitHub Free, inclusi controlli dei branch/required checks applicabili al piano. Registrare protezioni effettive, regola “nessun merge automatico”, collaboratori/App autorizzati, permessi Actions/secrets/environments e l'eventuale uso di Pages. Gestire eventuali domini Pages prima del cutover; non modificare i workflow per aggirare un limite del piano.
4. Controllare separatamente il connettore del **worker ChatGPT** e quello del **Job Watch Daily**: repository selezionato, account/App proprietario, approvazione organizzativa se presente, credenziali che consentano lettura privata, prompt e ricorrenza mantenuti. L'accesso del connettore dell'operatore/Codex non prova quello delle ricorrenze. Il percorso del worker resta bridge v2 a coda; `expected_job_key` non diventa un selettore.
5. Scegliere una destinazione già privata su disco cifrato, fuori da qualsiasi checkout, 0700. Generare/conservare offline una propria identità age e provarne la lettura su dispositivo di recupero. Fornire al comando solo il destinatario pubblico. Due copie cifrate indipendenti e un digest fidato separato; nessun artifact Actions, upload nella PR, backup in Git o chiave nel vault del codice pubblico.
6. Registrare privatamente impostazioni non-Git necessarie al recupero. Non salvare valori di token nei report; usare riferimenti al gestore credenziali. Esaminare l'esposizione storica separatamente: privatizzare non ritira fork pubblici, clone o copie già scaricate.

Fonti ufficiali controllate il 2026-10-30: [conseguenze della visibilità](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility), [billing Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [budget e blocco utilizzo](https://docs.github.com/en/billing/how-tos/set-up-budgets). Le quote e il piano vanno verificati nell'account alla data del cutover; non sono dedotti dal successo del preflight.

## 2. Checkpoint e backup nella finestra senza scritture

Sospendere temporaneamente le ricorrenze esterne con controllo dell'operatore e conservare gli orari da ripristinare. Scegliere una finestra fra le schedulazioni GitHub, attendere completamento di run e code; verificare nessuna richiesta bridge in volo/non riconciliata. Il tool non sospende né cancella nulla. Non disabilitare i workflow per far passare i controlli: devono risultare attivi. Se parte un writer o cambia un riferimento, interrompere e acquisire un nuovo checkpoint; mai alterare la coda o i dati per “stabilizzarli”.

Esempio POSIX, dalla root del checkout dello strumento; variabili da impostare privatamente prima di eseguire. `JW_PRIVATE_DIR` è una directory 0700 fuori da Git; `JW_RECIPIENT` è la chiave pubblica, `JW_IDENTITY` il percorso della chiave 0600. Usare nomi nuovi a ogni tentativo. Non abilitare `set -x`. I token sono forniti tramite ambiente da un gestore credenziali; non incollarli nella shell o nei comandi.

```sh
umask 077
git fetch origin main
JW_CHECKPOINT=$(git rev-parse origin/main)
python tools/privacy_cutover.py preflight --online --phase before --out "$JW_PRIVATE_DIR/before.json"
# Exit 2 è atteso per i gate manuali: verificarli individualmente prima di proseguire.
python tools/privacy_cutover.py continuity --commit "$JW_CHECKPOINT" --out "$JW_PRIVATE_DIR/engine-before.json"
python tools/privacy_cutover.py backup --recipient "$JW_RECIPIENT" --out "$JW_PRIVATE_DIR/repository.age"
# Trascrivere il capsule_sha256 restituito nel registro fidato separato, come JW_CAPSULE_SHA256.
python tools/privacy_cutover.py verify --capsule "$JW_PRIVATE_DIR/repository.age" --identity "$JW_IDENTITY" --sha256 "$JW_CAPSULE_SHA256"
python tools/privacy_cutover.py restore --capsule "$JW_PRIVATE_DIR/repository.age" --identity "$JW_IDENTITY" --sha256 "$JW_CAPSULE_SHA256" --target "$JW_PRIVATE_DIR/rehearsal.git"
python tools/privacy_cutover.py --root "$JW_PRIVATE_DIR/rehearsal.git" continuity --commit "$JW_CHECKPOINT" --baseline "$JW_PRIVATE_DIR/engine-before.json" --out "$JW_PRIVATE_DIR/engine-restored.json"
```

Verificare digest e decifrabilità anche della seconda copia. Il restore ha successo solo se coincidono refs, HEAD, inventario oggetti e fsck; la continuity deve restituire `CONTINUITY_MATCH`. Condividere esclusivamente codici di esito e conteggi. Non aprire `git show`, manifest o record in una registrazione pubblica. Conservare SHA del checkpoint e ora fissa presenti nell'evidenza privata. Se qualsiasi gate automatico è `BLOCKED`, o un manuale non è soddisfatto, STOP. Non usare `ready=false` come autorizzazione implicita.

## 3. Conversione manuale futura e accettazione

Solo dopo approvazione esplicita e chiusura di tutti i gate: il proprietario cambia **una sola impostazione di visibilità sul repository esistente** in GitHub Settings. Non vengono cambiati nomi, URL, commit, regole, workflow, branch, identità o dati. La CLI non offre un comando che esegua questo passo.

Prima di riprendere le ricorrenze, sullo stesso checkout dello strumento e stesso checkpoint:

```sh
python tools/privacy_cutover.py preflight --online --phase after --baseline "$JW_PRIVATE_DIR/before.json" --out "$JW_PRIVATE_DIR/after.json"
git fetch origin main
python tools/privacy_cutover.py continuity --commit "$JW_CHECKPOINT" --baseline "$JW_PRIVATE_DIR/engine-before.json" --out "$JW_PRIVATE_DIR/engine-after.json"
```

`PREFLIGHT_CHECKPOINT_MATCH` richiede repository ID/main SHA invariati, documenti/workflow/local HEAD invariati, transizione public→private e accesso autenticato privato reale. Se main è avanzato nel frattempo, il confronto è **inconclusivo**, non una regressione attribuita alla visibilità: interrompere e riconciliare la finestra, senza sovrascrivere l'evidenza o modificare l'ora di valutazione. La continuity confronta lo stesso SHA e la stessa ora, anche se il motore operativo procede dopo la finestra.

Controlli di servizio indispensabili, separati dal test deterministico:

- Lettura privata autenticata dai due connettori e lettura negata da una sessione anonima. Un token personale valido, da solo, non prova i permessi del worker o di Daily.
- Riprendere le ricorrenze agli orari originali; osservare la prima esecuzione naturale di raccolta/sync e la prima esecuzione worker e Daily dopo il cutover. Nessun dispatch o richiesta bridge di prova in questa PR. Se manca un lavoro reale per il worker, il ciclo no-op deve rispettare il contratto, non creare un job o una decisione fittizia.
- Controllare metadati di run ed esiti senza copiare log: writer serializzati, nessuna decisione utente modificata dal worker, identità/alias/fingerprint e chiusure preservati, Daily coerente con fonti e snapshot aggiornato. PR #25 resta aperta e invariata salvo incarichi propri. Nessuna conferma del comando web prima dell'esito GitHub e futura proiezione D1 verificata.

Il cutover è concluso solo dopo questi controlli reali. I test sintetici e il bundle non provano da soli l'esecuzione delle ricorrenze private.

## 4. Recupero e rollback senza ripubblicare dati

Se accessi/automazioni falliscono: mantenere il repository privato, sospendere solo le ricorrenze esterne coinvolte con stato annotato, ripristinare autorizzazioni App/connettore e billing gratuito; riprendere il workflow esistente dopo la correzione. Non rendere nuovamente pubblici dati personali come rollback automatico. Nessun force push, reset del motore, ricreazione del repository o replay indiscriminato delle richieste bridge.

Se si sospetta perdita Git, congelare le scritture con intervento dell'operatore, acquisire e confrontare privatamente gli SHA attuali, ripetere `verify`/`restore` in una **nuova** directory e confrontare checkpoint e continuità. Il repository bare ripristinato non ha remote: nessun push viene effettuato automaticamente. Definire una riparazione distinta e autorizzata che conservi anche i commit successivi al checkpoint; non sostituire main con una fotografia precedente. Ripristinare i metadati GitHub e i secret dalla custodia separata, non dal bundle.

Un eventuale ritorno a pubblico richiede una decisione separata del proprietario, valutazione dell'esposizione e un nuovo incarico: non fa parte di questo runbook eseguibile né della PR 1. Ripristinare gli orari e registrare privatamente incidenti ed esiti, mantenendo redatte le comunicazioni pubbliche.
