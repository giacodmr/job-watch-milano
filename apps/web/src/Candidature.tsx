import {useEffect,useRef,useState} from 'react';
import type {FormEvent,ReactNode} from 'react';
import {ApiError,dateLabel} from './api';
import {
  readPersonalPage,readPersonalSummary,readPersonalDetail,personalReadError,
  decisionLabel,reconciliationLabel,safeExternalUrl,
} from './model-c-personal-client';
import type {PersonalRow,PersonalPage,PersonalSummary,PersonalDetail,PersonalView,Decision,PersonalFilters} from './model-c-personal-client';
import {WorkspaceShell,CompanyAvatar,FitValue,JWIcon} from './components/CandidaturePrimitives';

const views:{key:PersonalView;title:string;description:string}[]=[
  {key:'all',title:'Tutte',description:'Tutti i riferimenti personali'},
  {key:'to_apply',title:'Da candidare',description:'Interessanti, da valutare o salvate'},
  {key:'applied',title:'Inviate',description:'Decisioni APPLIED o riferimenti candidatura'},
  {key:'dismissed',title:'Scartate',description:'Decisioni negative o riferimenti scartati'},
];
type Section='Riepilogo'|'Selezione'|'Retribuzione'|'Documenti';
const sections:Section[]=['Riepilogo','Selezione','Retribuzione','Documenti'];
const absent='Non registrato';
function displayDate(date:string|null){return date?dateLabel(date):'—';}
function Fact({name,children}:{name:string;children:ReactNode}){
  return <div className="c-fact"><dt>{name}</dt><dd>{children}</dd></div>;
}
function Provenance({commit,path}:{commit:string;path:string}){
  const safeCommit=/^[a-f0-9]{40}$/.test(commit);
  const safePath=path&&!path.startsWith('/')&&!path.split('/').includes('..');
  const url=safeCommit&&safePath?
    'https://github.com/giacodmr/job-watch-milano/blob/'+commit+'/'+path.split('/').map(encodeURIComponent).join('/'):null;
  return url?<a href={url} target="_blank" rel="noopener noreferrer" className="c-text-link">Fonte GitHub</a>:<span>{absent}</span>;
}

function CandidatureDrawer({selected,onClose}:{selected:PersonalRow;onClose:()=>void}){
  const dialog=useRef<HTMLDialogElement>(null);
  const [section,setSection]=useState<Section>('Riepilogo');
  const [detail,setDetail]=useState<PersonalDetail|null>(null);
  const [error,setError]=useState<string|null>(null);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{
    const active=document.activeElement;
    dialog.current?.showModal();
    return ()=>{
      dialog.current?.close();
      if(active instanceof HTMLElement)active.focus();
    };
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError(null);setDetail(null);
    readPersonalDetail(selected.jobId,controller.signal).then(result=>{
      if(!controller.signal.aborted)setDetail(result);
    }).catch(err=>{
      if(!controller.signal.aborted)setError(personalReadError(err));
    }).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[selected.jobId]);
  const row=detail?.job??selected;
  const title=row.catalog?.title||row.capturedTitle||'Ruolo non registrato';
  const company=row.catalog?.company||'Azienda non disponibile';
  const link=safeExternalUrl(row.catalog?.applyUrl||row.catalog?.canonicalUrl||row.officialUrl);
  return <dialog ref={dialog} className="c-drawer" aria-labelledby="c-drawer-title"
    onCancel={event=>{event.preventDefault();onClose();}}
    onClick={event=>{if(event.target===event.currentTarget)onClose();}}>
    <div className="c-drawer-panel">
      <header className="c-drawer-head">
        <div><small>Dettaglio personale · sola lettura</small>
          <h2 id="c-drawer-title">{title}</h2>
          <p>{company}{row.catalog?.location?' · '+row.catalog.location:''}</p>
        </div>
        <button type="button" className="c-icon-button" aria-label="Chiudi dettaglio" onClick={onClose}>
          <JWIcon name="close"/>
        </button>
      </header>
      <nav className="c-drawer-tabs" aria-label="Sezioni candidatura">
        {sections.map(item=><button key={item} type="button"
          aria-current={section===item?'page':undefined} onClick={()=>setSection(item)}>
          {item}</button>)}
      </nav>
      <div className="c-drawer-body">
        {loading&&<p className="c-informative" role="status">Caricamento storico personale…</p>}
        {error&&<div className="c-informative c-error" role="alert">{error}</div>}
        {detail&&!loading&&!error&&<>
          {section==='Riepilogo'&&<>
            <section className="c-panel-section"><h3>Posizione</h3>
              <dl className="c-facts">
                <Fact name="Azienda">{company}</Fact>
                <Fact name="Ruolo">{title}</Fact>
                <Fact name="Località">{row.catalog?.location||absent}</Fact>
                <Fact name="Disponibilità">{row.currentlyVisible?'Presente nel catalogo':'Riferimento storico'}</Fact>
                <Fact name="Decisione">{row.decision?decisionLabel[row.decision]:'Nessuna decisione registrata'}</Fact>
                <Fact name="Riferimenti">{row.activeReferences.join(' · ')||'Nessuno'}</Fact>
                <Fact name="Ultima decisione">{displayDate(row.decidedAt)}</Fact>
                <Fact name="Riconciliazione">{reconciliationLabel[row.reconciliation]}</Fact>
              </dl>
            </section>
            <section className="c-panel-section"><h3>Provenienza</h3>
              <dl className="c-facts">
                <Fact name="Identità"><code className="c-wrap">{row.jobId}</code></Fact>
                <Fact name="Origine"><Provenance commit={row.capturedCommit} path={row.capturedPath}/></Fact>
              </dl>
              {link&&<a href={link} target="_blank" rel="noopener noreferrer" className="c-btn c-btn-dark">
                Apri annuncio ufficiale <JWIcon name="arrow" size={14}/>
              </a>}
            </section>
          </>}
          {section==='Selezione'&&<>
            <section className="c-panel-section"><h3>Valutazione personale</h3>
              {row.assessment?<dl className="c-facts">
                <Fact name="Metodo">{row.assessment.method}</Fact>
                <Fact name="FIT"><FitValue row={row}/></Fact>
                <Fact name="Validità">{row.assessment.freshness==='CURRENT'?'Sul fingerprint corrente':row.assessment.freshness==='STALE'?'Versione precedente':'Non verificabile'}</Fact>
                <Fact name="Sintesi">{row.assessment.summary||absent}</Fact>
              </dl>:<p className="c-informative">Nessun assessment registrato.</p>}
            </section>
            <section className="c-panel-section"><h3>Storico delle decisioni</h3>
              {detail.decisionEvents.length?<ol className="c-history">
                {detail.decisionEvents.map(event=><li key={event.id}>
                  <strong>{decisionLabel[event.decision]}</strong><small>{displayDate(event.decidedAt)}</small>
                  {event.reasonSummary&&<p>{event.reasonSummary}</p>}
                  <Provenance commit={event.sourceCommit} path={event.sourcePath}/>
                </li>)}
              </ol>:<p className="c-informative">Nessuna decisione storica disponibile.</p>}
              {detail.decisionEventsTruncated&&<p className="c-informative">Sono visibili solo gli ultimi 50 eventi.</p>}
            </section>
            <section className="c-panel-section"><h3>Storico delle valutazioni</h3>
              {detail.assessmentEvents.length?<ol className="c-history">
                {detail.assessmentEvents.map(event=><li key={event.id}>
                  <strong>{event.method}</strong><small>{displayDate(event.analyzedAt)}</small>
                  <p>{event.fitScore===null?'FIT non registrato':'FIT '+event.fitScore}
                    {event.fingerprint!==row.assessment?.fingerprint?' · Fingerprint storico':''}
                  </p>
                  <Provenance commit={event.sourceCommit} path={event.sourcePath}/>
                </li>)}
              </ol>:<p className="c-informative">Nessun assessment storico disponibile.</p>}
              {detail.assessmentEventsTruncated&&<p className="c-informative">Sono visibili solo gli ultimi 50 eventi.</p>}
            </section>
          </>}
          {section==='Retribuzione'&&<section className="c-panel-section"><h3>Dati retributivi</h3>
            <p className="c-informative">Non sono ancora disponibili nel contratto PERSONAL attuale. Non vengono generate stime né offerte fittizie.</p>
          </section>}
          {section==='Documenti'&&<section className="c-panel-section"><h3>Documenti collegati</h3>
            <p className="c-informative">Il collegamento ai documenti esterni sarà disponibile con il registro candidature persistente. Nessun caricamento di file.</p>
          </section>}
        </>}
      </div>
      <footer className="c-drawer-footer"><span>Sola lettura · Nessuna modifica ai dati</span>
        <button type="button" className="c-btn" onClick={onClose}>Chiudi</button>
      </footer>
    </div>
  </dialog>;
}

export function CandidatureTable({items,onSelect}:{items:PersonalRow[];onSelect?:(row:PersonalRow)=>void}){
  return <div className="c-table-scroll"><table className="c-listing">
    <thead><tr><th>Posizione</th><th>Decisione / riferimento</th><th>FIT</th><th>Disponibilità</th><th>Ultima decisione</th><th><span className="c-sr-only">Dettaglio</span></th></tr></thead>
    <tbody>{items.map(row=>{
      const company=row.catalog?.company||'Azienda non disponibile';
      const role=row.catalog?.title||row.capturedTitle||'Ruolo non registrato';
      const decision=row.decision?decisionLabel[row.decision]:
        row.activeReferences.length?'Riferimento '+row.activeReferences.join(', '):'Nessuna decisione';
      return <tr key={row.jobId}><td><div className="c-job-cell">
        <CompanyAvatar name={row.catalog?.company??null}/>
        <span className="c-position"><strong>{role}</strong>
          <small>{company}{row.catalog?.location?' · '+row.catalog.location:''}</small>
        </span></div></td>
        <td><span className="c-stage"><i className={row.decision==='NOT_INTERESTED'?'c-dot c-dot-gray':'c-dot'}/>{decision}</span>
          <small className="c-mobile-sub">{reconciliationLabel[row.reconciliation]}</small>
        </td>
        <td><FitValue row={row}/></td>
        <td>{row.currentlyVisible?'Corrente':'Storica'}</td>
        <td>{displayDate(row.decidedAt)}</td>
        <td><button type="button" className="c-row-open" onClick={()=>onSelect?.(row)}
          disabled={!onSelect} aria-label={'Apri dettaglio di '+role}><JWIcon name="chevron"/></button></td>
      </tr>;
    })}</tbody>
  </table></div>;
}

export default function Candidature(){
  const [view,setView]=useState<PersonalView>('all');
  const [searchInput,setSearchInput]=useState('');
  const [search,setSearch]=useState('');
  const [decision,setDecision]=useState<Decision|''>('');
  const [reference,setReference]=useState<''|'SAVED'|'APPLICATION'|'DISMISSED'>('');
  const [cursor,setCursor]=useState<string|null>(null);
  const [previous,setPrevious]=useState<string[]>([]);
  const [refresh,setRefresh]=useState(0);
  const [page,setPage]=useState<PersonalPage|null>(null);
  const [summary,setSummary]=useState<PersonalSummary|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState<string|null>(null);
  const [selected,setSelected]=useState<PersonalRow|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true);setError(null);setPage(null);setSelected(null);
    const filters:PersonalFilters={view,q:search,limit:25};
    if(decision)filters.decision=decision;
    if(reference)filters.reference=reference;
    if(cursor)filters.cursor=cursor;
    Promise.all([readPersonalSummary(controller.signal),readPersonalPage(filters,controller.signal)]).then(([context,result])=>{
      if(controller.signal.aborted)return;
      if(context.catalogRevision!==result.catalogRevision||context.personalRevision!==result.personalRevision)
        throw new ApiError('CONTEXT_CHANGED');
      setSummary(context);setPage(result);
    }).catch(err=>{if(!controller.signal.aborted)setError(personalReadError(err));})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[view,search,decision,reference,cursor,refresh]);
  function resetPage(){setCursor(null);setPrevious([]);}
  function changeView(v:PersonalView){setView(v);resetPage();}
  function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();setSearch(searchInput.trim().slice(0,120));resetPage();}
  function clear(){setSearchInput('');setSearch('');setDecision('');setReference('');setView('all');resetPage();setRefresh(x=>x+1);}
  function reload(){resetPage();setRefresh(x=>x+1);}
  function next(){if(!page?.nextCursor)return;setPrevious(x=>[...x,cursor??'']);setCursor(page.nextCursor);}
  function back(){if(!previous.length)return;const last=previous.at(-1);setPrevious(x=>x.slice(0,-1));setCursor(last||null);}
  return <WorkspaceShell>
    <header className="c-heading">
      <div><h1>Candidature</h1><p>Le posizioni che segui, le tue decisioni e lo storico registrato.</p></div>
      <button type="button" className="c-btn" onClick={reload} disabled={loading}><JWIcon name="refresh" size={14}/> Aggiorna</button>
    </header>
    <section className="c-content" aria-label="Elenco candidature">
      <div className="c-tabs" role="tablist" aria-label="Viste personali">
        {views.map(item=><button key={item.key} type="button" role="tab"
          aria-selected={view===item.key} title={item.description}
          onClick={()=>changeView(item.key)}>{item.title}</button>)}
      </div>
      <form className="c-tools" role="search" onSubmit={submit}>
        <label className="c-search-field"><JWIcon name="search" size={15}/>
          <span className="c-sr-only">Cerca nel titolo catturato</span>
          <input type="search" maxLength={120} value={searchInput} onChange={e=>setSearchInput(e.target.value)}
            placeholder="Cerca nel ruolo salvato"/>
        </label>
        <button className="c-btn c-btn-search" type="submit">Cerca</button>
        <div className="c-filter-actions">
          <label><span className="c-sr-only">Filtra per decisione</span>
            <select value={decision} onChange={e=>{setDecision(e.target.value as Decision|'');resetPage();}}>
              <option value="">Tutte le decisioni</option>
              {Object.entries(decisionLabel).map(([value,label])=><option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label><span className="c-sr-only">Filtra per riferimento</span>
            <select value={reference} onChange={e=>{setReference(e.target.value as typeof reference);resetPage();}}>
              <option value="">Tutti i riferimenti</option>
              <option value="SAVED">Salvate</option><option value="APPLICATION">Candidature</option>
              <option value="DISMISSED">Scartate</option>
            </select>
          </label>
          <button type="button" className="c-clear" onClick={clear}>Reimposta</button>
        </div>
      </form>
      <p className="c-filter-hint">Ricerca e filtri applicati all’intero registro PERSONAL, non soltanto alla pagina visibile.</p>
      {loading&&<div role="status" className="c-state">Caricamento candidature…</div>}
      {!loading&&error&&<div className="c-state c-error" role="alert"><h2>Consultazione non disponibile</h2>
        <p>{error}</p><button className="c-btn" type="button" onClick={reload}>Riprova</button>
      </div>}
      {!loading&&!error&&page&&page.items.length>0&&<CandidatureTable items={page.items} onSelect={setSelected}/>}
      {!loading&&!error&&page&&page.items.length===0&&<div className="c-state">
        <h2>Nessuna posizione in questa vista</h2>
        <p>{page.total===0?'Nessun riferimento personale corrisponde ai filtri selezionati.':'Nessun altro risultato disponibile.'}</p>
        <button type="button" className="c-btn" onClick={clear}>Mostra tutte</button>
      </div>}
      <footer className="c-foot"><span>{page&&!loading?String(page.total)+' riferimenti nella vista':'Sola lettura'}{summary?' · '+summary.counts.decisionsCount+' decisioni registrate':''}</span>
        <div className="c-pager">
          <button className="c-btn" type="button" disabled={loading||previous.length===0} onClick={back}>Precedente</button>
          <span>Pagina {previous.length+1}</span>
          <button className="c-btn" type="button" disabled={loading||!page?.nextCursor} onClick={next}>Successiva</button>
        </div>
      </footer>
    </section>
    <p className="c-lab-note">Model C · ambiente locale sintetico · consultazione read-only. Il registro non modifica candidature o decisioni.</p>
    {selected&&<CandidatureDrawer selected={selected} onClose={()=>setSelected(null)}/>}
  </WorkspaceShell>;
}
