---
name: job-watch-ui-direction
description: Definisce la direzione estetica e UX di Job Watch quando si progettano, implementano o modificano interfacce. Si applica insieme a frontend-design; non si applica ai task esclusivamente backend.
---

- Visione estetica: precision editorial × operational software.
- Job Watch è un sistema operativo professionale e data-dense per la ricerca lavorativa, non una landing page SaaS generica.
- Design sobrio, raffinato, coerente e molto leggibile.
- Tipografia intenzionale, gerarchie nette, spacing system e design tokens riutilizzabili.
- Tabelle opportunità, filtri, navigazione, code semantiche e stati delle candidature con UX eccellente.
- Palette neutra, un accent color funzionale, colori semantici per gli stati.
- Evitare categoricamente AI slop: gradienti viola, glow, glassmorphism gratuito, card KPI giganti e ripetitive, emoji ornamentali, animazioni superflue, layout da template generico.
- Accessibilità, responsive desktop/mobile, empty/loading/error states.
- Nessun dato, job, KPI o stato inventato come reale.
- Design sempre integrato con gli effettivi contratti dati e le funzionalità del progetto.
- Preservare architettura esistente, database reale, GitHub, requisiti di sicurezza e zero costi aggiuntivi.

## Direzione Jet-inspired approvata — 30 ottobre 2026

Jet HR è il riferimento estetico per ordine visivo, sidebar, tipografia, input, tabelle, bordi e layout operativo. Non copiarne marchio, icone proprietarie, codice HTML/CSS, asset o script. La pagina marketing HTML consegnata dall'utente è materiale di riferimento, non una libreria da incorporare. Il risultato deve essere identificabile come **Job Watch**, non come Jet HR.

### Tokens iniziali di Job Watch (non palette ufficiale Jet HR)

- Ink `#19231b`, Dark `#182319`, Canvas `#f7f9f5`, Surface `#ffffff`.
- Border `#e1e7de`, Soft `#f1f4ed`, Lime `#d8ed97` (accento raro, mai sfondo dominante).
- Accent focus `#386b44`; colori semantici distinti per decisioni, priorità, disponibilità e stato pipeline.
- Font stack iniziale `Inter, Helvetica Neue, Arial, system-ui, sans-serif` senza font remoti o asset non autorizzati.
- Spaziature prevedibili; raggio 6–10px per componenti e contenitori; tabelle dense e facilmente leggibili.

### Regole di prodotto

- Sidebar desktop persistente e navigazione mobile esplicita; una gerarchia di pagina chiara.
- Prima il contenuto decisionale: vacancy, azienda, sede, priorità, decisione, provenienza e freschezza.
- KPI solo da snapshot confermati. Se la sincronizzazione manca, mostrare `—` e un empty state esplicito, non numeri dimostrativi confondibili con dati reali.
- Le fixture sintetiche devono avere avvisi visibili, mai essere presentate come annunci veri, ed essere isolate da scritture.
- Pulsanti di funzioni future disabilitati o non presenti: niente azioni che fingano di aver scritto su GitHub.
- Preferire HTML semantico + CSS con componenti React/TSX esistenti; no dipendenze di design, servizi web o cambio di stack.
- Introdurre un componente riutilizzabile quando almeno due viste lo richiedono, senza astrarre prematuramente ogni elemento.
- La prima iterazione comprende Dashboard e Vacancy Explorer con ricerca e filtri client-side sintetici; ogni espansione va validata prima nel browser con confronto desktop/mobile.

### Criteri per dichiarare una UI pronta

- Focus e selezioni da tastiera; etichette per input, indicatori di pagine e stati; contrasto sufficiente.
- Desktop 1440px, tablet 768px, mobile 390px e 320px senza sovrapposizioni o perdita di dati importanti.
- Verificare filtri, ricerca, dettaglio, sidebar mobile, reset e stato API locale in caricamento/errore/migrazione.
- Nessun deploy, D1 remoto, modifica Python, collector o dati operativi per una revisione puramente visuale.

### Integrazione con dati reali

- Dopo l'integrazione delle letture D1 della PR #25, Dashboard e Opportunità usano solo API locali e checkpoint confermati; la prima demo della PR #29 rimane un riferimento visivo storico, non una sorgente dati da ripristinare.
- Conservare filtri server, cursori, alias, provenienza e cronologia osservata. KPI mancanti sono indisponibili, non zero; campi non esposti non vengono stimati.
- Le azioni senza backend confermato restano esplicitamente disabilitate. Le preferenze fra dispositivi non possono essere dichiarate salvate con il solo URL o localStorage.
