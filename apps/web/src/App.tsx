import { useCallback, useEffect, useRef, useState } from 'react';
import { healthSchema } from '../shared/contracts';
import type { Health } from '../shared/contracts';

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const pending = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError(null);
    setHealth(null);
    try {
      const response = await fetch('/api/health', {
        signal: controller.signal,
        cache: 'no-store',
      });
      const body = healthSchema.safeParse(await response.json());
      if (!body.success || ![200, 503].includes(response.status))
        throw new Error('invalid_health');
      if (!controller.signal.aborted) setHealth(body.data);
    } catch {
      if (!controller.signal.aborted)
        setError(
          'API locale non raggiungibile. Avvia npm run dev:api e riprova.',
        );
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh();
    return () => pending.current?.abort();
  }, [refresh]);

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href="/">
          JW<span>Job Watch</span>
        </a>
        <span className="local-label">AMBIENTE LOCALE</span>
      </header>
      <main>
        <div className="eyebrow">PIATTAFORMA PERSONALE / FASE 0</div>
        <h1>
          Una base solida.
          <br />
          <span>Il prossimo passo è la connessione.</span>
        </h1>
        <p className="intro">
          Uno spazio per consultare aziende, opportunità e analisi del tuo Job
          Watch. Le fondamenta sono pronte per essere verificate in locale.
        </p>
        <section className="status-panel" aria-labelledby="status-title">
          <div className="panel-heading">
            <div>
              <div className="eyebrow">VERIFICA TECNICA</div>
              <h2 id="status-title">Stato dell’applicazione</h2>
            </div>
            <button onClick={() => void refresh()} disabled={loading}>
              {loading ? 'Verifica in corso…' : 'Verifica di nuovo'}
            </button>
          </div>
          <div role="status" aria-live="polite" aria-busy={loading}>
            {loading && <p>Controllo dell’API e del database locale…</p>}
            {error && <p className="error">{error}</p>}
            {health && (
              <>
                <dl className="health-grid">
                  <div>
                    <dt>API locale</dt>
                    <dd>
                      <span className="dot" />
                      Raggiungibile
                    </dd>
                  </div>
                  <div>
                    <dt>Database locale</dt>
                    <dd>
                      {health.database === 'ready'
                        ? 'Schema pronto'
                        : health.database === 'migration_required'
                          ? 'Migrazione richiesta'
                          : 'Da inizializzare'}
                    </dd>
                  </div>
                  <div>
                    <dt>Sincronizzazione</dt>
                    <dd>Non attiva</dd>
                  </div>
                  <div>
                    <dt>Accesso alla produzione</dt>
                    <dd>Disabilitato</dd>
                  </div>
                </dl>
                <p className="check-time">
                  Verifica:{' '}
                  {new Date(health.checkedAt).toLocaleString('it-IT', {
                    timeZone: 'Europe/Rome',
                  })}{' '}
                  · Europe/Rome
                </p>
                {health.database !== 'ready' && (
                  <p className="error">
                    Esegui <code>npm run db:migrate:local</code> nella cartella
                    apps/web.
                  </p>
                )}
              </>
            )}
          </div>
        </section>
        <section className="foundation" aria-labelledby="foundation-title">
          <div>
            <div className="eyebrow">CONFINI CHIARI</div>
            <h2 id="foundation-title">Il Job Watch continua a lavorare.</h2>
          </div>
          <p>
            Collector, workflow e analisi ChatGPT restano indipendenti. Questa
            applicazione non legge ancora i dati GitHub e non invia comandi ai
            processi operativi.
          </p>
        </section>
        <aside className="data-note">
          <strong>Nessun dato operativo importato.</strong>
          <span>
            I KPI e l’inventario saranno disponibili dopo l’implementazione
            della sincronizzazione di sola lettura.
          </span>
        </aside>
      </main>
      <footer>
        Job Watch · Architecture & Foundation<span>React / Workers / D1</span>
      </footer>
    </div>
  );
}
