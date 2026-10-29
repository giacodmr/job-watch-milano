# Job Watch — configurazione frontend design (Fase 0.5)

Configurazione locale Codex, eseguita il 2026-10-29 sul branch `codex/web-phase-zero`, partendo da `b6d0b92aa2912af7e6d13316b16094b96277d4d8`. Il worktree era pulito e la PR delle fondazioni [#23](https://github.com/giacodmr/job-watch-milano/pull/23) era aperta. Il fetch ha rilevato main a `3238964af936748691ab8db28d3674e16dda3d84`: nessun merge o modifica di quei checkpoint operativi è necessario per questa configurazione.

## Installazione eseguita

Dalla root del repository, con Node **24.15.0**, npm **11.12.1** e Skills CLI **1.7.4**:

```sh
npx --yes skills add anthropics/skills --skill frontend-design -a codex -y
npx --yes skills add vercel-labs/agent-skills --skill web-design-guidelines -a codex -y
```

Entrambi i comandi sono riusciti, senza fallback. L'assenza di `--global` mantiene lo scope nel repository; `-a codex` seleziona Codex. La CLI ha copiato le skill in `.agents/skills/` e creato `skills-lock.json`. Nessuna modifica a Node, package.json, lockfile o dipendenze dell'applicazione; la CLI usa la cache npm esterna al progetto.

## File e provenienza

- `.agents/skills/frontend-design/SKILL.md` e `LICENSE.txt`: copia ufficiale [Anthropic frontend-design](https://github.com/anthropics/skills/tree/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design). Ref upstream verificato: `ca45fc496a3436251f191354091d557da31c15b5`; blob Git SKILL `a5333457c414d20d625f307df945842c0952ecc3`, licenza `f433b1a53f5b830a205fd2df78e2b34974656c7b`.
- `.agents/skills/web-design-guidelines/SKILL.md`: copia ufficiale [Vercel web-design-guidelines](https://github.com/vercel-labs/agent-skills/tree/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/skills/web-design-guidelines). Ref upstream verificato: `1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62`; blob Git SKILL `ceae92ab319216a68274168fba9b63b998b65997`.
- `.agents/skills/job-watch-ui-direction/SKILL.md`: skill locale con `name` e `description` YAML validi e le regole estetiche richieste, conservate testualmente.
- `skills-lock.json`: sorgenti e hash di integrità delle due skill installate dalla CLI. La skill scritta localmente non richiede una voce upstream inventata.
- `AGENTS.md`: aggiunta una sezione frontend; tutte le regole precedenti restano intatte. I tre link puntano direttamente ai rispettivi SKILL.md.
- Questo documento: istruzioni di handoff, provenienza e verifiche della sola Fase 0.5.

Le copie ufficiali non sono state adattate o riscritte. La direzione specifica di Job Watch costituisce il brief che ne guida l'applicazione; non autorizza template generici, contenuti inventati o cambiamenti di architettura.

## Riconoscimento e verifica effettivi

```sh
npx --yes skills list -a codex
git hash-object .agents/skills/frontend-design/SKILL.md
git hash-object .agents/skills/frontend-design/LICENSE.txt
git hash-object .agents/skills/web-design-guidelines/SKILL.md
git diff --check
```

La CLI elenca tutte e tre sotto **Project Skills**, ciascuna con agente **Codex**: sorgenti `anthropics/skills`, `vercel-labs/agent-skills` e `local`. Tutti e tre gli SKILL.md sono stati realmente aperti e letti dall'agente in questo checkout; percorsi risolti dentro la root e file leggibili. I blob delle copie installate coincidono con quelli ottenuti dall'API GitHub ai ref sopra, inclusa la licenza Anthropic.

Il validatore ufficiale `skill-creator/scripts/quick_validate.py` è stato eseguito su tutte e tre le directory. PyYAML 6.0.3 è stato installato esclusivamente in un virtualenv temporaneo esterno al repository per eseguire quel validatore; nessuna dipendenza Python o Node del progetto aggiunta. Verificati inoltre la conservazione integrale del precedente AGENTS.md e i link ai tre file, anche partendo dalla directory `apps/web`.

La [documentazione ufficiale Codex](https://learn.chatgpt.com/docs/build-skills) indica `.agents/skills/` come percorso di discovery repository, anche dalle sottodirectory. Le nuove skill saranno utilizzabili dal prossimo turno; se il selettore non si aggiorna, riaprire la sessione. Questa verifica dimostra leggibilità, struttura e riconoscimento locale; non pretende di certificare un comportamento UI futuro mediante un task applicativo non richiesto.

## Uso obbligatorio nei prossimi task UI

Prima di progettare o modificare interfacce: leggere **frontend-design** e **job-watch-ui-direction**. Revisionare ogni implementazione con **web-design-guidelines**. Quando è disponibile un browser/preview, verificare davvero desktop e mobile, documentare le evidenze e correggere/riverificare i difetti prima di dichiarare completato il task. I task esclusivamente backend sono esclusi da queste skill.

La skill Vercel recupera le linee guida aggiornate da `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` prima di ogni revisione: richiede accesso di rete in quel momento. Se non disponibile, dichiarare il limite senza simulare una revisione completata. Le skill e i controlli visivi non concedono autorizzazione a deploy, nuovi costi o scritture operative.

## Confine della consegna

Nessuna modifica a `apps/web/`, database, contratti, frontend, dati GitHub, collector, workflow o dipendenze applicative. Nessun redesign, review della UI corrente o verifica visiva dell'app è stato avviato in questa fase di configurazione. Le verifiche applicative della Fase 0 non sono state rieseguite: il codice è invariato. La Fase 1 resta da avviare soltanto su incarico esplicito.
