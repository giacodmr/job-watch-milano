# Prova reale worker — 7 ottobre 2026

Prova eseguita da questa sessione Codex sul branch `refactor/job-state-simplification`, con lettura live delle fonti ufficiali e valutazioni semantiche reali. Non è ancora una prova della task ricorrente ChatGPT: autorizzazioni, avvio unattended e collegamento cloud al runner devono essere verificati separatamente. Main e pianificazione non sono stati modificati.

## Cinque vacancy selezionate da JW1

| Vacancy | Esito | Evidenza determinante |
|---|---|---|
| Mastercard R-278732 — Manager, Localization & Transformation | Reportable, fit 88 | Analisi, strategic intelligence, KPI e storytelling executive; nessuna gestione persone obbligatoria o soglia numerica di esperienza esplicita; anni e salary da verificare |
| Mastercard R-292698 — Director Legal Compliance | Non reportable, fit 22 | Specialismo financial-crime/AML/crypto e qualifica professionale obbligatoria; nessun filtro basato soltanto sul titolo |
| Mastercard R-291798-1 — Director, SME Global Market Expansion | Non reportable, fit 42 | Almeno 12 anni esplicitamente richiesti, oltre a ownership globale di crescita/GDV/ricavi |
| Zurich 1373963257 — Professionista della perizia Auto | Non reportable, fit 18 | Tre anni richiesti, ma anche abilitazione e iscrizione come perito auto; range ufficiale EUR 38–45k + 6% variabile |
| American Express 26013626 — Analyst-Risk Management | Non reportable, fit 74 | Credit analysis/underwriting junior; 1–2 anni e tedesco preferiti, non obbligatori; sotto soglia Londra 80 |

JD complete lette, mai salvate nel repository o in un cache file. Le decisioni conservano URL ufficiali, data di verifica, requisiti obbligatori/preferiti e motivazione. Nessuna scelta utente è stata creata/modificata; nessuna history surfaced è stata inventata. Il ruolo reportable entra nella Daily come opportunità ancora da comunicare.

## Problema trovato e corretto durante la prova

La pagina Oracle Candidate Experience di American Express restituisce una shell JavaScript, senza JD nel testo HTML. Il fallback generico quindi falliva. Il worker ora identifica il backend pubblico dalla pagina ufficiale, recupera i soli campi esterni della requisition e controlla ID e titolo. Se backend, ID, titolo o descrizione non corrispondono, restituisce errore e non genera una decisione. Nessun campo interno o JD non corrispondente viene usato.

Tre regression test coprono shell vuota, contenuto esterno completo, esclusione dei campi interni, requisition/titolo errati, descrizione mancante, backend non riconosciuto e mismatch URL/ID. Il template `DAILY_PROMPT.txt` è aggiornato a JD just-in-time e responsabilità separate Daily/worker; questo aggiornamento del file non modifica il prompt salvato della task ChatGPT esistente.

## Risultato verificato

| Batch | Pending prima | Pending dopo |
|---|---:|---:|
| JW1 | 46 | 41 |
| JW2 | 20 | 20 |
| JW3 | 3 | 3 |
| JW4 | 7 | 7 |
| Totale | 76 | 71 |

Applicazione atomica: cinque decisioni. Replay dello stesso packet: zero aggiornamenti. Le memorie JW2/JW3/JW4 restano byte-identiche. La selezione successiva comincia da American Express 26014697, poi Satispay e ING; nessuna delle cinque già analizzate ritorna nel packet. Preflight, input validation, **91 unittest**, sync reale, strict validation e due sync con Daily byte-identica passano. Health resta NEEDS_REVIEW: nessuna dichiarazione artificiale di completamento operativo.

## Passaggio necessario prima delle ricorrenze

Provare selezione, review e persistenza dalla task ChatGPT effettiva, senza assumere che abbia accesso al checkout o che il suo connettore consenta le stesse scritture di questa sessione. Solo dopo quella verifica collegare un worker ricorrente che processi tutti i batch a rotazione, con checkpoint piccoli, e mantenere una Daily distinta per il reporting. Lo smaltimento iniziale e quello futuro devono usare lo stesso processo automatico; nessun reset/cancellazione della coda.
