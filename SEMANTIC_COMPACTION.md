# Riduzione successiva della memoria semantic

L'utente ha autorizzato anche l'abbreviazione delle vecchie evidenze, oltre alla deduplica. La riduzione interviene su `job_memory_jw1..jw4.json`; non modifica inventory, business rule, soglie, decisioni utente o history dei messaggi effettivamente mostrati.

## Risultato sullo snapshot

| Batch | Byte prima | Byte dopo | Review abbreviate | Review protette |
|---|---:|---:|---:|---:|
| JW1 | 910,233 | 653,799 | 115 | 153 |
| JW2 | 4,370,259 | 2,784,724 | 242 | 769 |
| JW3 | 258,339 | 203,666 | 6 | 86 |
| JW4 | 520,747 | 400,106 | 53 | 121 |
| Totale | 6,059,578 | 4,042,295 | 416 | 1,129 |

Risparmio: **2,017,283 byte (33.3%)**. Tre contributi separati: 972,226 byte di indentazione eliminata, 313,378 byte di evidenza storica abbreviata, 731,679 byte di testi ripetuti deduplicati. Le 182 altre review storiche non vengono abbreviate perché prive dei campi interessati o senza risparmio sufficiente. Restano tutte le 1,727 review, 226 scelte utente e 133 history surfaced delle memorie; la scelta unresolved ION resta nel receipt della prima migrazione.

I byte hot della prima fase scendono ulteriormente da 9,302,000 a **7,284,717** (incluso priority receipt Amazon). Non è una stima di token: Daily e packet non caricavano già la memoria integrale, quindi la riduzione riguarda soprattutto storage, trasferimenti e lettura dello stato.

## Contratto e guardrail

- Protezione di ogni identità presente nel current, anche UNKNOWN, di tutti gli alias URL dello stesso employer e delle scelte INTERESTED/TO_REVIEW, incluse vacancy chiuse.
- Abbreviazione deterministica di esperienza/scope (200 caratteri) e requisiti (prime tre voci per lista, 140 caratteri ciascuna); ellissi e numero di voci omesse rendono visibili i tagli. Le altre evidenze verbose vengono sostituite da questo insieme ridotto, senza generare nuove conclusioni.
- Conservazione esatta di rationale finale, fit, metodo/data/fingerprint, anni obbligatori e preferiti, people-management/IC, livello/esito esperienza, salary/fonti, L.68/99 e twin checks. Tutte le chiavi vacancy e le sezioni identity/user/surfacing restano identiche.
- `historical_evidence.source_sha256` identifica la decisione completa precedente. Alla riapertura, anche su alias o stesso fingerprint, la review abbreviata non è valida: packet/Daily richiedono una nuova analisi full-JD. APPLIED/NOT_INTERESTED continuano a sopprimere la review ordinaria. A parità di data, una nuova review completa prevale sul vecchio alias abbreviato.
- Testi semantic identici sono salvati una volta per batch, con hash e riferimento interno. L'espansione è esatta; hash errato, riferimento assente/malformato, pool inutilizzato o encoding sconosciuto falliscono senza inventare campi. Le patch esterne non possono inviare riferimenti o receipt di abbreviazione per superare i controlli.
- Writer Daily, worker, lifecycle e migrazione producono il medesimo formato; journal/recovery conservano atomicità e isolamento. Ogni riscrittura elimina dal pool le stringhe non più usate. Un record per riga mantiene diff localizzati.

I guardrail delle nuove review rimangono completi. Il formato storico ridotto non costituisce una scorciatoia di validazione. Il testo tagliato non è duplicato in un altro file caldo/freddo; resta recuperabile dal commit precedente nella storia Git.

## Verifica e manutenzione

`python compact_job_memory.py` è un dry-run; `--apply` applica sotto lock, con una transazione sui quattro batch. Prima di scrivere confronta l'intera proiezione operativa di ogni batch, incluse queue e alias, e richiede equivalenza. Il receipt contiene hash sorgenti, hash decoded prima/dopo, hash delle proiezioni e byte per ogni fase. Ripetere il comando sullo stesso snapshot non riscrive file o receipt.

I test permanenti coprono roundtrip/deduplica, corruzione, mancanza di riferimenti, input esterni, no-JD, protezione current/UNKNOWN/alias/scelte attive, riapertura con fingerprint identico, nuova review obbligatoria, APPLIED/NOT_INTERESTED, commit/replay worker, writer Daily, dry-run/idempotenza e recovery journal. La validazione completa comprende preflight, input validation, unittest, sync, strict validation e due proiezioni Daily byte-identiche.
