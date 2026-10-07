# Manutenzione leggera, settimanale

Leggi il riepilogo health e le sezioni `partial_remediation` dell'audit; non ripercorrere ogni ATS nella Daily. Priorità: Amazon/Mastercard, aziende ad alto valore, mapping FULL con coverage PARTIAL e adapter che falliscono ripetutamente. Cambia un mapping/adapter solo dopo prova su fonte ufficiale e test di paginazione/ID. Non cambiare label per ottenere VERIFIED.

Usa `company_candidates.json` come staging manuale: verifica ruoli ufficiali, aggiorna last_seen/evidenze e applica le condizioni esistenti di promozione/pruning. Non esiste un collector automatico per quei record; non fingere che la lista sia stata verificata ogni giorno. Deep discovery e nuovi mapping si fanno qui, preservando la ricerca leggera daily.

Backlog: completa le 20 righe assegnate dopo il delta. A regime si riduce quando il ritmo di completamento supera gli arrivi. Per recupero storico dedicato, rigenera localmente il worklist con un limite più alto usando `build_worklist(backlog_limit=...)`, poi usa gli stessi registri e validatori; non riclassificare il backlog come lavoro daily obbligatorio. Non scartare ruoli plausibili per arrivare a zero.

Nessuna nuova automazione settimanale è installata da questa modifica. Può essere eseguita in una chat dedicata o nella manutenzione ordinaria del repository.

Gli errori LOCAL_RECORD_ERROR/SOURCE_ERROR sono warning di manutenzione; riprova solo lo stage/source necessario. BATCH_ERROR espone una recovery action in health; gli altri batch restano utilizzabili. Static preflight e regressioni sono obbligatori nella CI `Validate Job Watch`; i workflow di produzione applicano guard runtime con isolamento e salvano checkpoint/health anche se la pubblicazione fallisce.
