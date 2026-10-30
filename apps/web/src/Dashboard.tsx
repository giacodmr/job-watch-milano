import { useEffect, useState } from 'react';
import { healthSchema } from '../shared/contracts';
import type { Health } from '../shared/contracts';
import { dashboardResponseSchema, snapshotResponseSchema } from '../shared/queries';
import type { DashboardResponse, JobView, SnapshotView } from '../shared/queries';
import { ApiError, dateLabel, errorMessage, labels, readApi } from './api';
import { Icon, SectionHeading } from './components';
import JobDetail from './JobDetail';
import SnapshotInfo from './SnapshotInfo';

const number = new Intl.NumberFormat('it-IT');
const complete = (value: boolean | null | undefined) => value == null ? 'Non disponibile' : value ? 'Completo' : 'Non completo';
export default function Dashboard({ onExplore }: { onExplore: () => void }) {
  const [refresh, setRefresh] = useState(0);
  const [snapshot, setSnapshot] = useState<SnapshotView | null>(null);
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [pendingImports, setPendingImports] = useState(0);
  const [selected, setSelected] = useState<JobView | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setData(null); setSnapshot(null); setSelected(null); setHealth(null); setHealthError(false);
    Promise.all([readApi('/api/snapshot', snapshotResponseSchema, controller.signal), readApi('/api/dashboard', dashboardResponseSchema, controller.signal)])
      .then(([context, result]) => {
        if (controller.signal.aborted) return;
        if ((context.snapshot?.id ?? null) !== result.snapshotId) throw new ApiError('SNAPSHOT_CHANGED');
        setSnapshot(context.snapshot); setPendingImports(context.pendingImports); setData(result);
      }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(errorMessage(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    void fetch('/api/health', { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]), cache: 'no-store' })
      .then(async response => { if (![200,503].includes(response.status)) throw new Error('INVALID_HEALTH'); return healthSchema.parse(await response.json()); })
      .then(result => { if (!controller.signal.aborted) setHealth(result); })
      .catch(() => { if (!controller.signal.aborted) setHealthError(true); });
    return () => controller.abort();
  }, [refresh]);
  const metrics = data?.metrics;
  const indicators = [
    ['Opportunità attive', metrics?.openJobs, 'NEW, STILL_OPEN e UPDATED'],
    ['Da analizzare', metrics?.pendingAnalysis, 'Include attese tecniche del motore'],
    ['Candidature inviate', metrics?.appliedDecisions, 'Decisioni APPLIED · tracker non attivo'],
    ['Fonti in catalogo', metrics?.sources, 'Fonti dello snapshot importato'],
  ] as const;
  return <>
    <div className="page-heading"><div><p className="page-kicker">Panoramica</p><h1>La tua ricerca, sotto controllo.</h1><p className="page-description">Un solo spazio per seguire opportunità, candidature e qualità delle fonti.</p></div><span className="phase-label">D1 locale · Sola lettura</span></div>
    {error ? <section role="alert" className="error-banner"><h2>Consultazione non disponibile</h2><p>{error}</p><button className="button-secondary" onClick={() => setRefresh(v => v + 1)}>Riprova lettura</button></section> : <section className="notice" aria-label="Stato dei dati" aria-live="polite"><Icon name="info"/><div><strong>{loading ? 'Lettura dello snapshot locale…' : snapshot ? 'Stai consultando uno snapshot confermato.' : 'Nessuno snapshot confermato.'}</strong><span>{snapshot ? `Fonti fino al ${dateLabel(snapshot.newestSourceAt)}. Import del ${dateLabel(snapshot.confirmedAt)}. Nessuna sincronizzazione live.` : 'I dati saranno disponibili dopo un import verificato. Nessuna opportunità o metrica viene simulata.'}</span>{!loading && pendingImports > 0 && <span>Import incompleto: resta visibile l’ultimo checkpoint confermato.</span>}</div></section>}
    <div className="metrics-row" aria-label="Indicatori dello snapshot confermato" aria-busy={loading}>{indicators.map(([label, value, hint]) => <div className="metric" key={label}><span>{label}</span><strong aria-label={value == null ? `${label}: non disponibile` : undefined}>{value == null ? '—' : number.format(value)}</strong><small>{hint}</small></div>)}</div>
    <div className="dashboard-grid">
      <section className="panel focus-panel"><SectionHeading title="Opportunità da seguire" description="Aperte e segnalabili o selezionate da te. Prima osservazione, poi fit." trailing={<a className="inline-tag" href="#opportunities">Vedi catalogo <Icon name="chevron" size={13}/></a>}/>
        {loading ? <div className="empty-state" role="status"><p>Lettura delle opportunità…</p></div> : error ? <div className="empty-state"><Icon name="info"/><h3>Elenco non disponibile</h3><p>Riprova la lettura per vedere i dati confermati.</p></div> : data?.highlights.length ? <ul className="focus-list">{data.highlights.map(job => <li key={job.id}><button className="focus-job" onClick={() => setSelected(job)} aria-label={`Apri dettagli: ${job.title || job.jobKey}`}><span className="company-mark" aria-hidden="true">{job.company.slice(0,2).toUpperCase()}</span><span className="focus-job-title"><strong>{job.title || 'Titolo non disponibile'}</strong><small>{job.company} · {job.location || 'Sede non disponibile'}</small><small>Prima osservazione: {dateLabel(job.firstSeenAt)}</small></span><span className="focus-job-fit">{job.fitScore == null ? 'Fit —' : `Fit ${job.fitScore}`}<small>{job.decision ? labels[job.decision] : 'Segnalabile'}</small></span><Icon name="chevron" size={17}/></button></li>)}</ul> : <div className="empty-state"><div className="empty-symbol"><Icon name="search" size={24}/></div><h3>{snapshot ? 'Nessuna opportunità in evidenza' : 'Nessuna vacancy importata'}</h3><p>{snapshot ? 'Questo snapshot non contiene offerte aperte segnalabili o selezionate da te. Puoi consultare tutto l’inventario.' : 'Importa uno snapshot verificato per consultare il catalogo locale.'}</p><button className="button-primary" onClick={onExplore}>Apri opportunità <Icon name="arrow" size={17}/></button></div>}
      </section>
      <section className="panel health-panel" aria-labelledby="health-title"><div className="panel-topline"><h2 id="health-title">Stato della piattaforma</h2><button type="button" className="icon-button" onClick={() => setRefresh(v => v + 1)} disabled={loading} aria-label="Aggiorna stato"><Icon name="refresh" size={17}/></button></div><p className="panel-intro">Controlli locali e stati osservati nelle fonti.</p><div aria-live="polite" aria-busy={loading}>
        <div className="health-row"><span><span className={`status-dot ${health ? 'positive' : healthError ? 'negative' : 'neutral'}`}/>API locale</span><strong>{health ? 'Raggiungibile' : healthError ? 'Non disponibile' : 'Verifica…'}</strong></div>
        <div className="health-row"><span>Database D1</span><strong>{health?.database === 'ready' ? 'Schema pronto' : health?.database === 'migration_required' ? 'Migrazione richiesta' : healthError ? 'Non disponibile' : health?.database === 'unavailable' ? 'Non pronto' : 'Verifica…'}</strong></div>
        <div className="health-row"><span>Import GitHub → D1</span><strong>{loading ? 'Lettura…' : error ? 'Non disponibile' : snapshot ? 'Checkpoint confermato' : 'Non presente'}</strong></div>
        <div className="health-row"><span>Raccolta osservata</span><strong>{snapshot?.collectionStatus || 'Non disponibile'}</strong></div>
        <div className="health-row"><span>Semantica completa</span><strong>{complete(snapshot?.fullSemanticComplete)}</strong></div>
        <div className="health-row"><span>Worker ChatGPT live</span><strong>Non collegato</strong></div>
        {healthError && <p className="health-error">API locale non raggiungibile. Verifica il server locale e riprova.</p>}
        {health && <p className="check-time">Controllo API: {dateLabel(health.checkedAt)}. Non certifica il completamento operativo.</p>}
      </div></section>
    </div>
    {snapshot && !error && <SnapshotInfo snapshot={snapshot}/>}
    <section className="workflow-panel" aria-labelledby="workflow-title"><div className="workflow-title"><h2 id="workflow-title">Dal monitoraggio alla decisione</h2><p>Provenienza reale e capacità disponibili in questo ambiente.</p></div><div className="workflow-steps"><div><span className="step-index">01</span><h3>Raccogli</h3><p>Fonti osservate: {dateLabel(snapshot?.newestSourceAt ?? null)}. Il motore Python resta l’autorità.</p></div><div><span className="step-index">02</span><h3>Valuta</h3><p>Daily osservato: {complete(snapshot?.dailyComplete)}. Le analisi sono distinte dalle scelte utente.</p></div><div><span className="step-index">03</span><h3>Segui</h3><p>Tracker candidature e promemoria non disponibili. Nessuna scrittura o modifica delle decisioni.</p></div></div></section>
    <footer className="page-footer"><span>GitHub / Python: autorità operativa · D1: consultazione locale</span><span>Nessun comando produttivo attivo</span></footer>
    {selected && snapshot && <JobDetail selected={selected} snapshotId={snapshot.id} commitSha={snapshot.commitSha} onClose={() => setSelected(null)}/>}
  </>;
}
