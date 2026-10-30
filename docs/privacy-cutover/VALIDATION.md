# Verifica effettiva e handoff — PR 1

Data: 2026-10-30. Repository: `giacodmr/job-watch-milano`. Baseline main analizzata: `b3540152d55b455dd485b167978e92a914a85fc7`. Branch dedicato: `codex/privacy-cutover-safety`, creato da main, distinto dal branch della PR #25 (`b84d7786e977602830f0c88b7afe5b47dc2da16d` al controllo iniziale). Nessuna modifica preesistente è stata sovrascritta. Il dettaglio dei file proposti è nel diff della PR.

## Controlli eseguiti

- Toolchain locale isolata: Python 3.14.2, Git 2.39.3, PyYAML 6.0.3 e requests 2.32.5 nella virtualenv esterna. Nessuna dipendenza applicativa o versione Node modificata. age/age-keygen 1.3.2, archivio ufficiale darwin-arm64 verificato con SHA-256 pubblicato nel metadato della release (`e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5`). Toolchain privata fuori dal checkout, non versionata.
- `PRIVACY_SAFETY_REQUIRE_AGE=1 python -m unittest -q test_privacy_safety`: **24 test PASS** con crittografia reale, non mock. Fixture esclusivamente sintetiche e temporanee. Copertura: branch/tag annotati/refs PR/HEAD detached, oggetti e storia, chiavi errate, manomissioni, SHA fidato errato, ref remoto in movimento, rifiuto LFS/submodule/shallow, tar duplicati/traversal, percorsi/file privati, mancata sovrascrittura, YAML sicuro, API GET-only/paginazione, accesso pubblico distinto da privato, confronto checkpoint e guardia di pubblicazione.
- Suite Python completa `python -m unittest -q`: **259 test PASS**, 22.418 secondi, in una copia temporanea di `git archive` della baseline con aggiunta dei soli moduli/test nuovi. Nessun test esegue la pipeline nel checkout operativo. Ambiente include age e PyYAML, quindi nessuna copertura crypto omessa.
- Preflight reale con GET anonimi GitHub: **32 controlli**, nessun `BLOCKED`, `automated_checks_pass=true`, `ready=false` correttamente. Contratti dei quattro writer, trigger bridge, schedulazione, documenti, identità repository, lettura commit, workflow attivi e metadati artifact verificati. Nessun run attivo al momento dell'osservazione. Le autorizzazioni Actions amministrative e l'autenticazione privata non erano disponibili alla CLI; restano gate manuali. Nessun log o artifact scaricato.
- Prova reale remota autorizzata di backup cifrato e restore: **70 riferimenti pubblicizzati, 10.313 oggetti**, circa 31,9 MB cifrati. Verifica temporanea e restore bare persistito nella sola directory privata della prova: `RESTORE_VERIFIED`, fsck, refs/HEAD e inventario oggetti identici, nessun remote configurato. Non sono stati eseguiti push, checkout o hook nel repository ripristinato.
- Motore reale al commit baseline: `continuity` nella copia isolata originale e nel repository ripristinato ha restituito **CONTINUITY_MATCH** a SHA e ora identici, incluse memorie, code, proiezioni, snapshot, Daily e readiness worker. Le fonti estratte non sono state modificate. Nessun collector o comando sync operativo eseguito.
- La prova reale ha utilizzato una **chiave effimera**: backup, chiave e restore sono stati eliminati al termine; verificata la rimozione della directory. Non è un backup durevole dell'utente e non sostituisce la futura prova con chiave sotto la sua custodia. Nessun payload di prova è incluso nella PR.
- Parsing AST dei nove file Python nuovi e `git diff --check`: PASS. `publish-check` vincola il diff agli strumenti, test, requirements separato, nuovo workflow CI, ignore e documentazione redatta. Revisione del diff necessaria oltre al controllo automatico dei formati di secret.

## CI e perimetro

Il nuovo workflow `privacy-safety.yml` esegue su pull request i test sintetici Python 3.12 e richiede age/age-keygen: l'assenza della dipendenza causa errore, non uno skip silenzioso. Non usa secret applicativi, cron, upload di artifact o dispatch produttivi. I workflow preesistenti non cambiano. La suite generale preesistente continua a funzionare senza installare le dipendenze opzionali della safety; il workflow dedicato assicura la copertura completa. Lo stato CI remoto corrente va letto nella PR sul relativo head, non dedotto dai test locali.

Il controllo `publish-check` è intenzionalmente specifico alla PR 1: future PR con altri file autorizzati devono definire il proprio perimetro. Le regole frontend non vengono applicate a questo lavoro esclusivamente backend/tooling; non sono state modificate UI o architettura della web app. Nessuna migrazione locale o remota eseguita.

## Gate residui prima di privatizzare

1. Proprietario: verificare piano/consumi condivisi, blocco delle spese extra e funzionalità/protezioni disponibili su repository privato.
2. Proprietario: garantire selezione e autorizzazioni private del connettore e delle due ricorrenze esterne ChatGPT, con successiva osservazione reale del worker e di Daily. Il codice non può interrogare le loro configurazioni esterne.
3. Proprietario: fornire un destinatario age pubblico con identità di recupero custodita separatamente e una destinazione privata durevole; eseguire restore delle due copie prima del cutover.
4. Operatore: finestra senza writer/richieste bridge pendenti, nuovo checkpoint immediatamente prima della conversione, stessa identità GitHub e nessuna modifica Git/configurazione durante il confronto.
5. Dopo un futuro incarico esplicito: prova reale di accesso privato, confronto degli stessi checkpoint e osservazione delle esecuzioni naturali. Questa PR non pretende di averli già superati.

I risultati riportati sono limitati all'istante della prova. La privatizzazione non cancella copie pubbliche precedenti e il bundle non contiene metadati GitHub o secret del servizio. Nessuna visibilità cambiata, merge, deploy, risorsa cloud, database remoto, dato produttivo o redesign Electric modificato.
