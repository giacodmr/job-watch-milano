# ADR 0001 — stack gratuito, isolamento e accesso privato

Stato: accettato per fondazioni locali; provisioning/deploy e autorizzazioni remote rinviati. Data verifica fonti: 2026-10-29.

## Decisione

Confermare React + TypeScript strict + Vite; Worker Cloudflare unico per API e asset; D1 SQL con migrazioni versionate; GitHub Actions già operativo come esecutore; ChatGPT Chat come worker esterno. Nessuna API LLM, broker, nuovo scheduler, ORM o servizio aggiuntivo. SQL esplicito e Zod sono sufficienti per schema e contratti. Dipendenze e runtime bloccati da lockfile; Node 24 LTS.

La directory `apps/web/` possiede dipendenze, configurazioni e test autonomi. Niente import Python nel runtime Worker, niente cambiamenti al sistema esistente. D1 è proiezione consultabile V1, GitHub resta autorità operativa.

## Limiti effettivi verificati

- **Workers Free:** 100.000 richieste/giorno, 10 ms CPU per invocazione, 128 MB memoria; 50 subrequest per richiesta. Gli asset statici serviti senza Worker hanno richieste gratuite illimitate. Con `run_worker_first: true` ogni asset passa dal codice e consuma quota Worker: scelta intenzionale per il futuro controllo di accesso su ogni percorso. Fonti: [limiti Workers](https://developers.cloudflare.com/workers/platform/limits/), [pricing](https://developers.cloudflare.com/workers/platform/pricing/), [asset billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/).
- **D1 Free:** 5 milioni di righe lette/giorno, 100.000 scritte/giorno, 5 GB aggregati account; massimo **500 MB per database**, 10 database, 50 query per invocazione Worker e 100 parametri per query, Time Travel 7 giorni. Il superamento delle quote blocca le query; non passare a Paid. Anche gli indici hanno costo di scrittura da misurare. Fonti: [pricing D1](https://developers.cloudflare.com/d1/platform/pricing/), [limiti D1](https://developers.cloudflare.com/d1/platform/limits/).
- **Cloudflare Zero Trust Free / Access:** fino a 50 utenti, retention log standard fino a 24 ore; adeguato a un'app personale, non a uno storico audit permanente. Audit applicativo in D1. Fonte: [piani Cloudflare, sezione Zero Trust](https://www.cloudflare.com/plans/). Nessun dominio a pagamento richiesto nella Fase 0; per un futuro workers.dev protetto verificare Access e chiudere ogni hostname alternativo/preview. Nessuna garanzia di configurazione account finché non viene ispezionata con autorizzazione.
- **GitHub Actions:** standard runner dei repository pubblici gratuiti; repository privati consumano quota condivisa account. La [pagina prezzi](https://github.com/pricing) indica 2.000 minuti/mese per Free; la [documentazione quote](https://docs.github.com/en/billing/reference/product-usage-included) esprime invece l'incluso compute come credito monetario (12 USD per GitHub Free) e 500 MB storage. Non assumere automaticamente 2.000 minuti disponibili o aggiuntivi per questa app: prima di abilitare operazioni ricorrenti verificare piano, saldo e budget account con stop-spesa a zero. Fonte: [billing Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Le quote sono condivise con altri usi dell'account. Non è stato possibile certificare disponibilità residua o policy di fatturazione degli account cloud senza provisioning/accesso account; la Fase 0 non li usa. La nuova CI usa un solo job Ubuntu, timeout 10 minuti, path filter, cancellazione run web superati, nessun artifact/cache supplementare o schedule. La CI Python già presente può avviarsi su tutte le PR e rimane invariata.

Verifica read-only dell'API GitHub del repository effettuata in questa fase: `private: false`, `visibility: public`. La CI proposta usa quindi runner standard su repository pubblico, entro il modello gratuito documentato. Le cautele sul budget privato diventano rilevanti se la visibilità o il tipo di runner cambiano; nessuna impostazione account è stata modificata.

## Controlli per costo zero

Mantenere piani Free e nessun upgrade automatico. Import incrementali per hash, chunk bounded, query indicizzate/paginate, no polling aggressivo, no JD integrali. Prima dell'import remoto misurare `meta.rows_read/rows_written`, dimensione DB e CPU; soglie applicative iniziali proposte: interrompere nuove sync a 70.000 righe scritte/giorno, 3.500.000 lette/giorno o 350 MB DB, lasciando margine agli indici e agli altri processi. Queste soglie non sostituiscono le quote account e non sono ancora implementate. In caso di limite: degradazione esplicita e retry dopo reset, mai acquisto di capacità. Versioni inutilizzate in staging potranno essere eliminate; conservazione history va definita dopo misura del primo import, senza cancellare decisioni o identità.

## Autenticazione e segreti

Fase 0: servizi legati a loopback, nessuna credenziale, accesso remoto rifiutato inclusi asset. Questo è sviluppo locale, **non** un'implementazione di Cloudflare Access. Il deploy è bloccato come requisito di processo e manca una configurazione produttiva.

Target: Access protegge intera app (HTML, JS e API), allowlist utente esplicita tramite IdP o OTP; il Worker verifica crittograficamente `Cf-Access-Jwt-Assertion` con JWKS, algoritmo atteso, issuer/team, audience e exp/nbf, cache delle chiavi e rotazione. Non fidarsi di header email o sola presenza del JWT. Tutti i percorsi workers.dev/custom domain/preview devono rispettare lo stesso controllo oppure essere disabilitati. Fonte: [application token](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/).

Ingestion servizio-servizio: policy Access **Service Auth** distinta e service token con client ID/secret server-side; il Worker deve autorizzare esplicitamente identità servizio e scope ingestion, senza attribuirgli capacità di scelta utente. Il login interattivo non è una credenziale CI; service token non va mai nel browser. Fonte: [service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/).

GitHub App installata solo sul repo, secret lato Worker e token brevi con permessi minimi quando l'adapter sarà definito. In lettura nessun contents:write. In mutation futura: allowlist azioni/path/ref, limiti body, stessa origin e CSRF per sessioni browser, no CORS permissivo, audit pseudonimo basato su identificatore opaco, mai email/secret/JD nei log. Stato comando confermato solo da evidenza Git verificata e successivo import.

## Alternative

Un backend Python cloud duplicherebbe l'operatività e imporrebbe un nuovo hosting. Un database esterno aggiunge connessioni e limiti/account. Pages separato è possibile, ma un Worker con asset evita due distribuzioni e mantiene stesso origin. Un ORM e un broker non risolvono l'atomicità GitHub/D1; staging e outbox SQL sono più piccoli e verificabili. Il costo CPU dei JWT va misurato prima del deploy sul piano Free: la cache JWKS non elimina la verifica della firma.

Conseguenze: nessuna promessa di consistenza istantanea cross-system; freschezza e stato pending visibili. Snapshot versionati aumentano storage ma rendono atomica la pubblicazione e possibile rollback del checkpoint. Unico ambiente implementato: locale.
