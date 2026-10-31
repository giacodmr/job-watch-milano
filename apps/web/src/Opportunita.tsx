import {useEffect,useRef,useState} from 'react';
import type {FormEvent,ReactNode} from 'react';
import {ApiError,dateLabel} from './api';
import {WorkspaceShell,CompanyAvatar,FitValue,JWIcon} from './components/CandidaturePrimitives';
import {PersonalActions} from './components/PersonalActions';
import {decisionLabel,reconciliationLabel,safeExternalUrl} from './model-c-personal-client';
import type {Opportunity,OpportunityPage,OpportunityDetail,OpportunitySnapshot,OpportunityFilters,OpportunityView} from './model-c-opportunities-client';
import {readOpportunityDetail,readOpportunities,readOpportunitySnapshot,resolveOpportunityPersonal} from './model-c-opportunities-client';

const views:{value:OpportunityView;label:string;description:string}[]=[
  {value:'all',label:'Tutte',description:'Tutte le vacancy correnti pubblicate'},
  {value:'new',label:'Nuove',description:'Lifecycle NEW nel catalogo'},
  {value:'updated',label:'Aggiornate',description:'Lifecycle UPDATED nel catalogo'},
  {value:'analysis',label:'Da analizzare',description:'Flag tecnico needsAnalysis nel catalogo'},
];
const lifecycleLabels={NEW:'Nuova',STILL_OPEN:'Aperta',UPDATED:'Aggiornata'} as const;
function date(value:string|null){return value?dateLabel(value):'—';}
function analysisLabel(row:Opportunity){
  if(row.technicalStatus)return 'Stato tecnico: '+row.technicalStatus;
  if(row.needsAnalysis===true)return row.workerEligible===false?'Analisi in attesa tecnica':'Da analizzare';
  if(row.needsAnalysis===false)return 'Nessuna analisi pendente segnalata';
  return 'Stato analisi non disponibile';
}
function Fact({label,children}:{label:string;children:ReactNode}){
  return <div className="c-fact"><dt>{label}</dt><dd>{children}</dd></div>;
}
function SourceLink({commit,path}:{commit:string;path:string}){
  const valid=/^[a-f0-9]{40}$/.test(commit)&&path&&!path.startsWith('/')&&!path.split('/').includes('..');
  const url=valid?'https://github.com/giacodmr/job-watch-milano/blob/'+commit+'/'+path.split('/').map(encodeURIComponent).join('/'):null;
  return url?<a className="c-text-link" href={url} target="_blank" rel="noopener noreferrer">Fonte GitHub</a>:<span>Non disponibile</span>;
}
function OpportunityDrawer({row,revision,personalAvailable,onClose,onConfirmed}:{
  row:Opportunity;revision:number;personalAvailable:boolean;onClose:()=>void;onConfirmed:()=>void;
}){
  const modal=useRef<HTMLDialogElement>(null);
  const [tab,setTab]=useState<'summary'|'analysis'|'source'|'history'>('summary');
  const [detail,setDetail]=useState<OpportunityDetail|null>(null);
  const [currentRevision,setCurrentRevision]=useState(revision);
  const [error,setError]=useState<string|null>(null);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{
    const focus=document.activeElement;modal.current?.showModal();
    return ()=>{modal.current?.close();if(focus instanceof HTMLElement)focus.focus();};
  },[]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError(null);setDetail(null);
    readOpportunityDetail(row.id,revision,controller.signal).then(result=>{
      if(!controller.signal.aborted)setDetail(result);
    }).catch(e=>{if(!controller.signal.aborted)setError(message(e));})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[row.id,revision]);
  async function reloadDetail(){
    const snapshot=await readOpportunitySnapshot(AbortSignal.timeout(15000));
    if(!snapshot)throw new Error('NO_PUBLISHED_CATALOG');
    const refreshed=await readOpportunityDetail(row.id,snapshot.syncRevision,AbortSignal.timeout(15000));
    setCurrentRevision(snapshot.syncRevision);setDetail(refreshed);setError(null);
  }
  const current=detail?.job??row;
  // A fresh, explicit null PERSONAL revision overrides a previously loaded list.
  const personalReady=detail?detail.personalRevision!==null:personalAvailable;
  const personal=personalReady?resolveOpportunityPersonal(row,detail):null;
  const link=safeExternalUrl(current.applyUrl)||safeExternalUrl(current.canonicalUrl);
  const title=current.title||'Ruolo non disponibile';
  const tabs:[typeof tab,string][]=[['summary','Riepilogo'],['analysis','Analisi'],['source','Provenienza'],['history','Storico personale']];
  return <dialog ref={modal} className="c-drawer" aria-labelledby="o-dialog-title"
    onCancel={event=>{event.preventDefault();onClose();}}
    onClick={event=>{if(event.target===event.currentTarget)onClose();}}>
    <div className="c-drawer-panel">
      <header className="c-drawer-head"><div><small>Dettaglio opportunità</small>
        <h2 id="o-dialog-title">{title}</h2><p>{current.company}{current.location?' · '+current.location:''}</p></div>
        <button className="c-icon-button" type="button" aria-label="Chiudi opportunità" onClick={onClose}><JWIcon name="close"/></button>
      </header>
      <nav className="c-drawer-tabs" aria-label="Sezioni opportunità">
        {tabs.map(([key,name])=><button type="button" key={key} aria-current={tab===key?'page':undefined}
          onClick={()=>setTab(key)}>{name}</button>)}
      </nav>
      <div className="c-drawer-body">
        {loading&&<p className="c-informative" role="status">Caricamento dettaglio opportunità…</p>}
        {error&&<p className="c-informative c-error" role="alert">{error}</p>}
        {!loading&&detail&&!error&&<>
          {tab==='summary'&&<>
            <section className="c-panel-section"><h3>Posizione</h3>
              <dl className="c-facts">
                <Fact label="Azienda">{current.company}</Fact><Fact label="Titolo">{title}</Fact>
                <Fact label="Località">{current.location||'Non disponibile'}</Fact>
                <Fact label="Lifecycle">{lifecycleLabels[current.lifecycle]}</Fact>
                <Fact label="Prima osservazione">{date(current.firstSeenAt)}</Fact>
                <Fact label="Ultima osservazione">{date(current.lastSeenAt)}</Fact>
                <Fact label="Decisione personale">{!personalReady?'Registro non disponibile':personal?.decision?decisionLabel[personal.decision]:'Nessuna decisione registrata'}</Fact>
                <Fact label="Riferimenti personali">{!personalReady?'Registro non disponibile':personal?.activeReferences.join(' · ')||'Nessuno'}</Fact>
              </dl>
              {link&&<a className="c-btn c-btn-dark" href={link} target="_blank" rel="noopener noreferrer">Apri annuncio ufficiale <JWIcon name="arrow" size={14}/></a>}
            </section>
            <PersonalActions row={personal} jobId={current.id}
              catalogRevision={detail.snapshot.syncRevision} onReload={reloadDetail} onConfirmed={onConfirmed}/>
          </>}
          {tab==='analysis'&&<section className="c-panel-section"><h3>Analisi e valutazione</h3>
            <dl className="c-facts">
              <Fact label="Stato analisi">{analysisLabel({...current,personal})}</Fact>
              <Fact label="Categoria">{current.kind==='AI_QUEUE'?'Coda AI':'Opportunità'}</Fact>
              <Fact label="Idoneità tecnica">{current.workerEligible===null?'Non disponibile':current.workerEligible?'Idonea':'Non idonea'}</Fact>
              <Fact label="FIT personale">{!personalReady?'Registro non disponibile':personal?<FitValue row={personal}/>:<span>—</span>}</Fact>
              <Fact label="Validità FIT">{personal?.assessment?.freshness==='CURRENT'?'Sul fingerprint corrente':
                personal?.assessment?.freshness==='STALE'?'Storico, fingerprint precedente':
                personal?.assessment?'Non verificabile':'Non disponibile'}</Fact>
              <Fact label="Metodo">{personal?.assessment?.method||'Non disponibile'}</Fact>
              <Fact label="Sintesi">{personal?.assessment?.summary||'Non registrata'}</Fact>
              <Fact label="Riconciliazione">{!personalReady?'Registro non disponibile':personal?reconciliationLabel[personal.reconciliation]:'Nessun riferimento personale'}</Fact>
            </dl>
          </section>}
          {tab==='source'&&<section className="c-panel-section"><h3>Identità e provenienza</h3>
            <dl className="c-facts">
              <Fact label="Job ID"><code className="c-wrap">{current.id}</code></Fact>
              <Fact label="Identità sorgente">{current.jobKey}</Fact>
              <Fact label="Batch">{current.batch||'Non disponibile'}</Fact>
              <Fact label="Revisione catalogo">{currentRevision}</Fact>
              <Fact label="Commit"><code className="c-wrap">{current.originCommit}</code></Fact>
              <Fact label="SHA-256"><code className="c-wrap">{current.originSha256}</code></Fact>
              <Fact label="Percorso"><code className="c-wrap">{current.originPath}</code></Fact>
              <Fact label="Fonte"><SourceLink commit={current.originCommit} path={current.originPath}/></Fact>
              <Fact label="Alias">{detail.aliases.length?detail.aliases.join(' · '):'Nessuno disponibile'}</Fact>
            </dl>
            {detail.aliasesTruncated&&<p className="c-informative">Sono mostrati soltanto i primi 50 alias.</p>}
          </section>}
          {tab==='history'&&<section className="c-panel-section"><h3>Storico personale</h3>
            {!detail.personalDetail&&<p className="c-informative">{personalReady?'Nessuna storia personale registrata per questa vacancy.':'Il registro personale non è ancora stato importato e verificato.'}</p>}
            {detail.personalDetail&&<>
              <h3>Decisioni</h3>
              {detail.personalDetail.decisionEvents.length?<ol className="c-history">
                {detail.personalDetail.decisionEvents.map(event=><li key={event.id}>
                  <strong>{event.decision?decisionLabel[event.decision]:'Decisione revocata'}</strong>
                  <small>{date(event.decidedAt)} · {event.origin==='APP'?'Piattaforma':'GitHub'}</small>
                  {event.reasonSummary&&<p>{event.reasonSummary}</p>}
                </li>)}
              </ol>:<p className="c-informative">Nessuna decisione storica disponibile.</p>}
              {detail.personalDetail.decisionEventsTruncated&&<p className="c-informative">Cronologia decisioni limitata agli ultimi 50 eventi.</p>}
              {!!detail.personalDetail.appEvents?.some(event=>event.kind==='SAVED')&&<>
                <h3>Salvataggi nella piattaforma</h3>
                <ol className="c-history">{detail.personalDetail.appEvents?.filter(event=>event.kind==='SAVED').map(event=>
                  <li key={event.id}><strong>{event.savedActive?'Posizione salvata':'Rimossa dai salvati'}</strong>
                    <small>{date(event.createdAt)} · Piattaforma</small></li>)}</ol>
              </>}
              <h3>Valutazioni</h3>
              {detail.personalDetail.assessmentEvents.length?<ol className="c-history">
                {detail.personalDetail.assessmentEvents.map(event=><li key={event.id}>
                  <strong>{event.method}</strong><small>{date(event.analyzedAt)}</small>
                  <p>{event.fitScore===null?'FIT non disponibile':'FIT '+event.fitScore}</p>
                </li>)}
              </ol>:<p className="c-informative">Nessuna valutazione storica disponibile.</p>}
              {detail.personalDetail.assessmentEventsTruncated&&<p className="c-informative">Cronologia valutazioni limitata agli ultimi 50 eventi.</p>}
            </>}
          </section>}
        </>}
      </div>
      <footer className="c-drawer-footer"><span>Azioni personali solo se autorizzate dal server</span>
        <button className="c-btn" type="button" onClick={onClose}>Chiudi</button>
      </footer>
    </div>
  </dialog>;
}
export function OpportunityTable({items,personalAvailable,onSelect}:{items:Opportunity[];personalAvailable:boolean;onSelect?:(item:Opportunity)=>void}){
  return <div className="c-table-scroll"><table className="c-listing o-listing">
    <thead><tr><th>Posizione</th><th>Lifecycle</th><th>Analisi</th><th>Decisione</th><th>FIT</th><th>Ultima osservazione</th><th><span className="c-sr-only">Dettaglio</span></th></tr></thead>
    <tbody>{items.map(row=>{
      const title=row.title||'Ruolo non disponibile';
      // Do not display stale PERSONAL values when the owner context is absent.
      const personal=personalAvailable?row.personal:null;
      return <tr key={row.id}>
        <td><div className="c-job-cell"><CompanyAvatar name={row.company}/>
          <span className="c-position"><strong>{title}</strong><small>{row.company}{row.location?' · '+row.location:''}</small>
          <small className="o-mobile-decision">{personal?.decision?decisionLabel[personal.decision]:personal?.activeReferences.length?'Riferimento '+personal.activeReferences.join(', '):personalAvailable?'Nessuna decisione':'Registro non disponibile'}{personal?.assessment?.fitScore!==null&&personal?.assessment?.fitScore!==undefined?' · FIT '+personal.assessment.fitScore+(personal.assessment.freshness==='CURRENT'?'':' storico'):''}</small></span>
        </div></td>
        <td>{lifecycleLabels[row.lifecycle]}</td>
        <td>{analysisLabel(row)}</td>
        <td>{personal?.decision?<span className="c-stage"><i className={personal.decision==='NOT_INTERESTED'?'c-dot c-dot-gray':'c-dot'}/>{decisionLabel[personal.decision]}</span>
          :personal?.activeReferences.length?'Riferimento '+personal.activeReferences.join(', '):<span className="c-muted">{personalAvailable?'Nessuna decisione':'Registro non disponibile'}</span>}</td>
        <td>{!personalAvailable?<span className="c-muted">—</span>:personal?<FitValue row={personal}/>:<span className="c-muted">—</span>}</td>
        <td>{date(row.lastSeenAt)}</td>
        <td><button type="button" className="c-row-open" disabled={!onSelect}
          aria-label={'Apri dettaglio '+title} onClick={()=>onSelect?.(row)}><JWIcon name="chevron"/></button></td>
      </tr>;
    })}</tbody>
  </table></div>;
}
function message(error:unknown) {
  const code=error instanceof ApiError?error.code:'';
  if(['CATALOG_CHANGED','CONTEXT_CHANGED','CURSOR_FILTER_MISMATCH','INVALID_CURSOR'].includes(code))
    return 'Il catalogo o i filtri sono cambiati. Aggiorna la consultazione.';
  if(code==='not_found')return 'L’API Model C è disabilitata. Questa vista è disponibile solo nel laboratorio sintetico locale.';
  if(code==='PERSONAL_CONTEXT_UNAVAILABLE')return 'Il registro personale non è ancora stato importato e verificato per questo accesso.';
  if(['NO_PUBLISHED_CATALOG','CATALOG_SCHEMA_MISMATCH'].includes(code))return 'Il catalogo non è ancora pronto per la consultazione.';
  if(code==='cloudflare_quota_exceeded')return 'La quota gratuita giornaliera del database è stata raggiunta. La consultazione sarà nuovamente possibile dopo il reset Cloudflare delle 00:00 UTC, senza modificare i dati.';
  if(code==='database_unavailable')return 'Il database non è temporaneamente disponibile. Riprova più tardi.';
  return 'Non è possibile consultare le opportunità al momento. Riprova più tardi.';
}
export default function Opportunita(){
  const [view,setView]=useState<OpportunityView>('all');
  const [qInput,setQInput]=useState('');
  const [q,setQ]=useState('');
  const [companyId,setCompanyId]=useState('');
  const [kind,setKind]=useState<''|'OPPORTUNITY'|'AI_QUEUE'>('');
  const [batch,setBatch]=useState<''|'jw1'|'jw2'|'jw3'|'jw4'>('');
  const [lifecycle,setLifecycle]=useState<''|'NEW'|'STILL_OPEN'|'UPDATED'>('');
  const [cursor,setCursor]=useState<string|null>(null);
  const [previous,setPrevious]=useState<string[]>([]);
  const [page,setPage]=useState<OpportunityPage|null>(null);
  const [snapshot,setSnapshot]=useState<OpportunitySnapshot>(null);
  const [selected,setSelected]=useState<Opportunity|null>(null);
  const [refresh,setRefresh]=useState(0);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState<string|null>(null);
  useEffect(()=>{
    const abort=new AbortController();setLoading(true);setError(null);setPage(null);
    const filters:OpportunityFilters={view,q,limit:25};
    if(companyId)filters.companyId=companyId;
    if(kind)filters.kind=kind;
    if(batch)filters.batch=batch;
    if(lifecycle&&view==='all')filters.lifecycle=lifecycle;
    if(cursor)filters.cursor=cursor;
    Promise.all([readOpportunitySnapshot(abort.signal),readOpportunities(filters,abort.signal)]).then(([head,results])=>{
      if(abort.signal.aborted)return;
      if(head?.syncRevision!==results.snapshot?.syncRevision || head?.runId!==results.snapshot?.runId)
        throw new ApiError('CATALOG_CHANGED');
      setSnapshot(head);setPage(results);
    }).catch(e=>{if(!abort.signal.aborted)setError(message(e));})
      .finally(()=>{if(!abort.signal.aborted)setLoading(false);});
    return ()=>abort.abort();
  },[view,q,companyId,kind,batch,lifecycle,cursor,refresh]);
  function reset(){setCursor(null);setPrevious([]);}
  function updateView(next:OpportunityView){setView(next);setLifecycle('');reset();}
  function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();setQ(qInput.trim().slice(0,120));reset();}
  function clear(){setView('all');setQ('');setQInput('');setCompanyId('');setKind('');setBatch('');setLifecycle('');reset();setRefresh(x=>x+1);}
  function reload(){reset();setRefresh(x=>x+1);}
  function next(){if(!page?.nextCursor)return;setPrevious(x=>[...x,cursor||'']);setCursor(page.nextCursor);}
  function back(){if(!previous.length)return;const prev=previous.at(-1);setPrevious(x=>x.slice(0,-1));setCursor(prev||null);}
  return <WorkspaceShell section="opportunita">
    <header className="c-heading">
      <div><h1>Opportunità</h1><p>Esplora le posizioni pubblicate dal motore Job Watch.</p></div>
      <button className="c-btn" type="button" disabled={loading} onClick={reload}><JWIcon name="refresh" size={14}/> Aggiorna</button>
    </header>
    {snapshot&&<p className="o-snapshot" role="status">
      {snapshot.currentJobs} vacancy correnti nel catalogo · Revisione {snapshot.syncRevision} · Commit {snapshot.observedCommit.slice(0,8)}
    </p>}
    {!loading&&!error&&snapshot&&page&&page.personalRevision===null&&<p className="o-snapshot" role="status">Catalogo disponibile in sola lettura. Il registro personale non è ancora stato importato e verificato per questo accesso; le decisioni non vengono mostrate.</p>}
    <section className="c-content" aria-label="Catalogo opportunità">
      <div className="c-tabs" role="tablist" aria-label="Viste catalogo">
        {views.map(item=><button key={item.value} type="button" role="tab"
          aria-selected={view===item.value} title={item.description}
          onClick={()=>updateView(item.value)}>{item.label}</button>)}
      </div>
      <form className="c-tools o-tools" role="search" onSubmit={submit}>
        <label className="c-search-field"><JWIcon name="search" size={15}/>
          <span className="c-sr-only">Cerca ruolo, azienda o località</span>
          <input value={qInput} onChange={e=>setQInput(e.target.value)} maxLength={120}
            placeholder="Cerca ruolo, azienda o località" type="search"/>
        </label>
        <button type="submit" className="c-btn c-btn-search">Cerca</button>
        <div className="c-filter-actions">
          <label><span className="c-sr-only">Azienda</span><select value={companyId}
            onChange={e=>{setCompanyId(e.target.value);reset();}}>
            <option value="">Tutte le aziende</option>
            {snapshot?.companies.map(item=><option value={item.id} key={item.id}>{item.name}</option>)}
          </select></label>
          <label><span className="c-sr-only">Tipologia</span>
            <select value={kind} onChange={e=>{setKind(e.target.value as typeof kind);reset();}}>
              <option value="">Tutte le tipologie</option><option value="OPPORTUNITY">Opportunità</option><option value="AI_QUEUE">Coda AI</option>
            </select></label>
          <label><span className="c-sr-only">Batch</span>
            <select value={batch} onChange={e=>{setBatch(e.target.value as typeof batch);reset();}}>
              <option value="">Tutti i batch</option>{(['jw1','jw2','jw3','jw4'] as const).map(item=><option key={item} value={item}>{item.toUpperCase()}</option>)}
            </select></label>
          <label><span className="c-sr-only">Lifecycle</span>
            <select value={lifecycle} disabled={view!=='all'} onChange={e=>{setLifecycle(e.target.value as typeof lifecycle);reset();}}>
              <option value="">Tutti gli stati</option>
              {Object.entries(lifecycleLabels).map(([key,name])=><option key={key} value={key}>{name}</option>)}
            </select></label>
          <button type="button" className="c-clear" onClick={clear}>Reimposta</button>
        </div>
      </form>
      <p className="c-filter-hint">Ricerca e filtri sul catalogo pubblicato completo. La vista «Da analizzare» usa il flag tecnico, non una raccomandazione AI.</p>
      {loading&&<div className="c-state" role="status">Caricamento catalogo…</div>}
      {!loading&&error&&<div className="c-state c-error" role="alert"><h2>Catalogo non disponibile</h2>
        <p>{error}</p><button className="c-btn" type="button" onClick={reload}>Riprova</button>
      </div>}
      {!loading&&!error&&!snapshot&&<div className="c-state">
        <h2>Nessun catalogo pubblicato</h2><p>Non è ancora disponibile uno snapshot CATALOG verificato. Non vengono mostrate vacancy fittizie.</p>
      </div>}
      {!loading&&!error&&page&&snapshot&&page.items.length>0&&<OpportunityTable items={page.items} personalAvailable={page.personalRevision!==null} onSelect={setSelected}/>}
      {!loading&&!error&&snapshot&&page&&page.items.length===0&&<div className="c-state">
        <h2>Nessuna opportunità nella vista</h2><p>Non ci sono vacancy che corrispondono ai filtri selezionati.</p>
        <button className="c-btn" type="button" onClick={clear}>Mostra tutte</button>
      </div>}
      <footer className="c-foot"><span>{page&&!loading?page.total+' opportunità nella vista':'Consultazione read-only'}
        {snapshot?.companiesTruncated?' · Elenco aziende limitato ai primi 500':''}</span>
        <div className="c-pager">
          <button className="c-btn" type="button" disabled={loading||!previous.length} onClick={back}>Precedente</button>
          <span>Pagina {previous.length+1}</span>
          <button className="c-btn" type="button" disabled={loading||!page?.nextCursor} onClick={next}>Successiva</button>
        </div>
      </footer>
    </section>
    <p className="c-lab-note">Model C · consultazione dei dati verificati · modifiche disponibili solo se autorizzate dal server.</p>
    {selected&&snapshot&&<OpportunityDrawer row={selected} revision={snapshot.syncRevision} personalAvailable={page?.personalRevision!==null} onClose={()=>setSelected(null)} onConfirmed={reload}/>}
  </WorkspaceShell>;
}
