import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { healthSchema } from '../shared/contracts';
import type { Health } from '../shared/contracts';

type Page = 'dashboard' | 'opportunities';
type IconName = 'grid' | 'search' | 'layers' | 'briefcase' | 'check' | 'activity' | 'settings' | 'arrow' | 'refresh' | 'menu' | 'close' | 'filter' | 'external' | 'info' | 'circle' | 'chevron';
type Decision = 'TO_REVIEW' | 'INTERESTED' | 'APPLIED';
type DemoJob = {
  id: string;
  company: string;
  initials: string;
  role: string;
  location: 'Milano' | 'Roma' | 'Remoto';
  priority: 'Alta' | 'Media';
  decision: Decision;
  team: string;
};

const demoJobs: readonly DemoJob[] = [
  { id: 'sample-1', company: 'Lumen Payments', initials: 'LP', role: 'Strategy & Operations Associate', location: 'Milano', priority: 'Alta', decision: 'TO_REVIEW', team: 'Strategy' },
  { id: 'sample-2', company: 'Arbor Digital', initials: 'AD', role: 'Business Analyst', location: 'Milano', priority: 'Alta', decision: 'INTERESTED', team: 'Business Operations' },
  { id: 'sample-3', company: 'Northlake Labs', initials: 'NL', role: 'Product Strategy Analyst', location: 'Roma', priority: 'Media', decision: 'TO_REVIEW', team: 'Product' },
  { id: 'sample-4', company: 'Meridian Mobility', initials: 'MM', role: 'Commercial Strategy Associate', location: 'Milano', priority: 'Alta', decision: 'APPLIED', team: 'Commercial' },
  { id: 'sample-5', company: 'Kora Commerce', initials: 'KC', role: 'Operations Analyst', location: 'Remoto', priority: 'Media', decision: 'TO_REVIEW', team: 'Operations' },
  { id: 'sample-6', company: 'Boreal Systems', initials: 'BS', role: 'Business Strategy Specialist', location: 'Roma', priority: 'Media', decision: 'INTERESTED', team: 'Strategy' },
];

const decisionLabels: Record<Decision, string> = {
  TO_REVIEW: 'Da valutare',
  INTERESTED: 'Interessante',
  APPLIED: 'Candidatura inviata',
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const shared = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.75, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const };
  return (
    <svg {...shared}>
      {name === 'grid' && <><rect x="3.5" y="3.5" width="7" height="7" rx="1"/><rect x="13.5" y="3.5" width="7" height="7" rx="1"/><rect x="3.5" y="13.5" width="7" height="7" rx="1"/><rect x="13.5" y="13.5" width="7" height="7" rx="1"/></>}
      {name === 'search' && <><circle cx="10.7" cy="10.7" r="6.8"/><path d="m16 16 4.7 4.7"/></>}
      {name === 'layers' && <><path d="m12 2.5 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 16.5l9 5 9-5"/></>}
      {name === 'briefcase' && <><rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12.5c5 3 13 3 18 0"/></>}
      {name === 'check' && <><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/></>}
      {name === 'activity' && <><path d="M3 18h18M4 14l5-5 4 3 7-8"/></>}
      {name === 'settings' && <><path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2.3" fill="var(--surface)"/><circle cx="16" cy="17" r="2.3" fill="var(--surface)"/></>}
      {name === 'arrow' && <><path d="M4 12h16m-6-6 6 6-6 6"/></>}
      {name === 'refresh' && <><path d="M20 11a8 8 0 0 0-14.5-4.5L3 9m0-5v5h5M4 13a8 8 0 0 0 14.5 4.5L21 15m0 5v-5h-5"/></>}
      {name === 'menu' && <path d="M4 7h16M4 12h16M4 17h16"/>}
      {name === 'close' && <path d="M5 5 19 19M19 5 5 19"/>}
      {name === 'filter' && <><path d="M4 5h16l-6 7v6l-4 2v-8L4 5Z"/></>}
      {name === 'external' && <><path d="M13 5h6v6M19 5l-8 8"/><path d="M19 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h4"/></>}
      {name === 'info' && <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/></>}
      {name === 'circle' && <circle cx="12" cy="12" r="7.5"/>}
      {name === 'chevron' && <path d="m9 6 6 6-6 6"/>}
    </svg>
  );
}

function NavigationItem({ icon, label, active, onClick, unavailable = false, href = '#' }: {
  icon: IconName; label: string; active?: boolean; onClick?: () => void; unavailable?: boolean; href?: string;
}) {
  const children = <><Icon name={icon}/><span>{label}</span>{unavailable && <span className="soon">Presto</span>}</>;
  if (unavailable) return <span className="nav-item nav-item-disabled" aria-disabled="true">{children}</span>;
  return <a className={`nav-item${active ? ' is-active' : ''}`} href={href} onClick={onClick} aria-current={active ? 'page' : undefined}>{children}</a>;
}

function SectionHeading({ title, description, trailing }: { title: string; description?: string; trailing?: ReactNode }) {
  return <div className="section-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{trailing}</div>;
}

function HealthPanel({ health, loading, error, refresh }: {
  health: Health | null; loading: boolean; error: string | null; refresh: () => void;
}) {
  const ready = health?.database === 'ready';
  return (
    <section className="panel health-panel" aria-labelledby="health-title">
      <div className="panel-topline"><h2 id="health-title">Stato della piattaforma</h2><button type="button" className="icon-button" onClick={refresh} disabled={loading} aria-label="Aggiorna stato"><Icon name="refresh" size={17}/></button></div>
      <p className="panel-intro">Controlli tecnici reali dell'ambiente locale.</p>
      <div role="status" aria-live="polite" aria-busy={loading}>
        <div className="health-row"><span><span className={`status-dot ${health ? 'positive' : loading ? 'neutral' : 'negative'}`}/>API locale</span><strong>{loading ? 'Verifica…' : health ? 'Raggiungibile' : 'Non disponibile'}</strong></div>
        <div className="health-row"><span><span className={`status-dot ${ready ? 'positive' : 'neutral'}`}/>Database D1</span><strong>{loading ? 'Verifica…' : ready ? 'Schema pronto' : health?.database === 'migration_required' ? 'Migrazione richiesta' : 'Non pronto'}</strong></div>
        <div className="health-row"><span><span className="status-dot neutral"/>Sincronizzazione</span><strong>Non attiva</strong></div>
        <div className="health-row"><span><span className="status-dot neutral"/>Produzione</span><strong>Disabilitata</strong></div>
        {error && <p className="health-error">{error}</p>}
        {health && health.database !== 'ready' && <p className="health-hint">Per inizializzare D1 esegui <code>npm run db:migrate:local</code>.</p>}
        {health && <p className="check-time">Ultimo controllo: {new Date(health.checkedAt).toLocaleString('it-IT', { timeZone: 'Europe/Rome' })}</p>}
      </div>
    </section>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>(() => window.location.hash === '#opportunities' ? 'opportunities' : 'dashboard');
  const [mobileMenu, setMobileMenu] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const pending = useRef<AbortController | null>(null);
  const [query, setQuery] = useState('');
  const [decision, setDecision] = useState<'ALL' | Decision>('ALL');
  const [location, setLocation] = useState('ALL');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setLoading(true);
    setError(null);
    setHealth(null);
    try {
      const response = await fetch('/api/health', { signal: controller.signal, cache: 'no-store' });
      const parsed = healthSchema.safeParse(await response.json());
      if (!parsed.success || ![200, 503].includes(response.status)) throw new Error('invalid_health');
      if (!controller.signal.aborted) setHealth(parsed.data);
    } catch {
      if (!controller.signal.aborted) setError('API locale non raggiungibile. Avvia npm run dev:api e riprova.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => pending.current?.abort();
  }, [refresh]);

  useEffect(() => {
    const syncFromHash = () => setPage(window.location.hash === '#opportunities' ? 'opportunities' : 'dashboard');
    window.addEventListener('hashchange', syncFromHash);
    return () => window.removeEventListener('hashchange', syncFromHash);
  }, []);

  const shownJobs = useMemo(() => demoJobs.filter((job) => {
    const term = query.trim().toLocaleLowerCase('it-IT');
    return (!term || `${job.company} ${job.role} ${job.team}`.toLocaleLowerCase('it-IT').includes(term)) &&
      (decision === 'ALL' || job.decision === decision) &&
      (location === 'ALL' || job.location === location);
  }), [query, decision, location]);

  const selectedJob = selectedId ? shownJobs.find((job) => job.id === selectedId) : undefined;
  const goTo = (next: Page) => {
    window.location.hash = next === 'opportunities' ? '#opportunities' : '#dashboard';
    setPage(next);
    setMobileMenu(false);
    setSelectedId(null);
  };

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Vai al contenuto principale</a>
      {mobileMenu && <button type="button" className="nav-backdrop" aria-label="Chiudi menu" onClick={() => setMobileMenu(false)}/>}
      <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`} aria-label="Navigazione principale">
        <div className="brand"><div className="brand-symbol" aria-hidden="true"><span className="mark-corner"/><span className="mark-block"/></div><span>job<span className="brand-light">watch</span></span></div>
        <div className="workspace"><span className="workspace-avatar">JW</span><div><strong>Il mio workspace</strong><small>Ambiente locale</small></div><Icon name="chevron" size={15}/></div>
        <nav className="nav-links" aria-label="Sezioni">
          <span className="nav-group-title">Il tuo spazio</span>
          <NavigationItem icon="grid" label="Dashboard" href="#dashboard" active={page === 'dashboard'} onClick={() => goTo('dashboard')}/>
          <NavigationItem icon="search" label="Opportunità" href="#opportunities" active={page === 'opportunities'} onClick={() => goTo('opportunities')}/>
          <NavigationItem icon="layers" label="Aziende" unavailable/>
          <NavigationItem icon="briefcase" label="Candidature" unavailable/>
          <span className="nav-group-title nav-group-gap">Operatività</span>
          <NavigationItem icon="check" label="Coda semantica" unavailable/>
          <NavigationItem icon="activity" label="Monitor" unavailable/>
          <div className="nav-bottom"><NavigationItem icon="settings" label="Impostazioni" unavailable/></div>
        </nav>
        <div className="sidebar-footer"><span className="side-footer-indicator"/>Prototipo frontend <span>v0.1</span></div>
      </aside>

      <div className="main-area">
        <header className="app-topbar">
          <div className="header-left">
            <button type="button" className="mobile-menu-button" onClick={() => setMobileMenu(!mobileMenu)} aria-label={mobileMenu ? 'Chiudi navigazione' : 'Apri navigazione'} aria-expanded={mobileMenu}><Icon name={mobileMenu ? 'close' : 'menu'} size={21}/></button>
            <span className="breadcrumb-root">Workspace</span><span className="breadcrumb-divider">/</span><strong>{page === 'dashboard' ? 'Dashboard' : 'Opportunità'}</strong>
          </div>
          <div className="header-right"><span className="demo-indicator"><span/>Modalità demo</span><span className="profile-icon" aria-label="Workspace personale">JW</span></div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          {page === 'dashboard' ? (
            <>
              <div className="page-heading"><div><p className="page-kicker">Panoramica</p><h1>La tua ricerca, sotto controllo.</h1><p className="page-description">Un solo spazio per seguire opportunità, candidature e qualità delle fonti.</p></div><span className="phase-label">Design preview · Fase 0</span></div>
              <section className="notice notice-neutral" aria-label="Informazione sui dati"><Icon name="info" size={18}/><div><strong>I dati operativi non sono ancora collegati.</strong><span>Questa schermata non mostra KPI inventati. I valori saranno disponibili dopo una sincronizzazione verificata.</span></div></section>
              <div className="metrics-row" aria-label="Indicatori in attesa di dati">
                {[['Opportunità attive','Dati non disponibili'], ['In valutazione','Dati non disponibili'], ['Candidature','Dati non disponibili'], ['Fonti monitorate','Dati non disponibili']].map(([label, hint]) => <div className="metric" key={label}><span>{label}</span><strong aria-label="Valore non disponibile">—</strong><small>{hint}</small></div>)}
              </div>
              <div className="dashboard-grid">
                <section className="panel focus-panel">
                  <SectionHeading title="Opportunità da seguire" description="Qui appariranno le vacancy prioritarie dopo il primo import." trailing={<span className="inline-tag">In preparazione</span>}/>
                  <div className="empty-state"><div className="empty-symbol"><Icon name="search" size={24}/></div><h3>Nessuna vacancy importata</h3><p>Puoi intanto esplorare il layout del catalogo con un piccolo set di dati sintetici.</p><button type="button" className="button-primary" onClick={() => goTo('opportunities')}>Apri la demo opportunità <Icon name="arrow" size={17}/></button></div>
                </section>
                <HealthPanel health={health} loading={loading} error={error} refresh={() => { void refresh(); }}/>
              </div>
              <section className="workflow-panel" aria-labelledby="workflow-title"><div className="workflow-title"><h2 id="workflow-title">Dal monitoraggio alla decisione</h2><p>Il percorso che Job Watch renderà consultabile nell'interfaccia.</p></div><div className="workflow-steps"><div><span className="step-index">01</span><h3>Raccogli</h3><p>Vacancy ufficiali e provenienza della fonte.</p></div><div><span className="step-index">02</span><h3>Valuta</h3><p>Revisione semantica distinta dalle tue decisioni.</p></div><div><span className="step-index">03</span><h3>Segui</h3><p>Stato delle candidature e aggiornamenti verificati.</p></div></div></section>
            </>
          ) : (
            <>
              <div className="page-heading"><div><p className="page-kicker">Esplora</p><h1>Opportunità</h1><p className="page-description">Un catalogo ordinato per scegliere su cosa concentrarti.</p></div><span className="phase-label">Vacancy Explorer · Demo</span></div>
              <section className="notice notice-demo" aria-label="Avviso dati dimostrativi"><Icon name="info" size={18}/><div><strong>Queste vacancy sono interamente inventate per testare l'interfaccia.</strong><span>Non provengono dai collector, non sono annunci reali e non modificano le decisioni salvate in GitHub.</span></div></section>
              <div className="explorer-panel">
                <SectionHeading title="Elenco opportunità" description="Ricerca e filtri operano solo sugli esempi locali." trailing={<span className="inline-tag">{shownJobs.length} esempi</span>}/>
                <div className="toolbar">
                  <label className="search-field"><Icon name="search" size={18}/><span className="sr-only">Cerca azienda o ruolo</span><input name="demo-search" autoComplete="off" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cerca azienda o ruolo…"/></label>
                  <label className="filter-select"><span className="sr-only">Filtra per decisione</span><Icon name="filter" size={16}/><select name="demo-decision" autoComplete="off" value={decision} onChange={(event) => setDecision(event.target.value as 'ALL' | Decision)}><option value="ALL">Tutte le decisioni</option><option value="TO_REVIEW">Da valutare</option><option value="INTERESTED">Interessante</option><option value="APPLIED">Candidatura inviata</option></select></label>
                  <label className="filter-select"><span className="sr-only">Filtra per località</span><select name="demo-location" autoComplete="off" value={location} onChange={(event) => setLocation(event.target.value)}><option value="ALL">Tutte le località</option><option value="Milano">Milano</option><option value="Roma">Roma</option><option value="Remoto">Remoto</option></select></label>
                  {(query || decision !== 'ALL' || location !== 'ALL') && <button type="button" className="reset-button" onClick={() => { setQuery(''); setDecision('ALL'); setLocation('ALL'); }}>Azzera filtri</button>}
                </div>
                <div className="table-scroll"><table className="jobs-table"><thead><tr><th scope="col">Azienda e ruolo</th><th scope="col">Località</th><th scope="col">Priorità</th><th scope="col">Decisione</th><th scope="col"><span className="sr-only">Dettaglio</span></th></tr></thead><tbody>{shownJobs.map((job) => <tr key={job.id} className={selectedId === job.id ? 'selected-row' : ''}><td><div className="company-cell"><span className="company-mark">{job.initials}</span><div><strong>{job.role}</strong><small>{job.company} · {job.team}</small></div></div></td><td>{job.location}</td><td><span className={`priority ${job.priority === 'Alta' ? 'priority-high' : ''}`}><span/>{job.priority}</span></td><td><span className={`decision decision-${job.decision.toLowerCase()}`}>{decisionLabels[job.decision]}</span></td><td><button type="button" className="row-action" onClick={() => setSelectedId(selectedId === job.id ? null : job.id)} aria-label={`Apri dettaglio di ${job.role}`} aria-expanded={selectedId === job.id}><Icon name="chevron" size={18}/></button></td></tr>)}</tbody></table></div>
                {shownJobs.length === 0 && <div className="no-results"><Icon name="search" size={25}/><strong>Nessun esempio corrisponde ai filtri.</strong><span>Modifica i filtri per vedere altre righe.</span></div>}
                <div className="table-footer"><span>Solo dati sintetici · Nessuna scrittura</span><span>{shownJobs.length} di {demoJobs.length} esempi</span></div>
              </div>
              {selectedJob && <section className="detail-panel" aria-label="Dettaglio esempio selezionato"><div className="detail-main"><p className="page-kicker">Scheda dimostrativa</p><h2>{selectedJob.role}</h2><p>{selectedJob.company} · {selectedJob.location} · {selectedJob.team}</p><div className="detail-tags"><span className="inline-tag">Priorità {selectedJob.priority.toLowerCase()}</span><span className="inline-tag">{decisionLabels[selectedJob.decision]}</span></div></div><div className="detail-right"><p>Quando sarà attiva la sincronizzazione, qui compariranno la fonte ufficiale, l'analisi disponibile e la cronologia verificata.</p><button type="button" className="button-secondary" onClick={() => setSelectedId(null)}>Chiudi dettaglio <Icon name="close" size={15}/></button></div></section>}
            </>
          )}
          <footer className="page-footer"><span>Job Watch · Anteprima design system</span><span>React + HTML semantico + CSS · Nessun deploy</span></footer>
        </main>
      </div>
    </div>
  );
}
