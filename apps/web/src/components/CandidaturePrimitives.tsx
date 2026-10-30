import {useState} from 'react';
import type {ReactNode} from 'react';
import type {PersonalRow} from '../model-c-personal-client';

type IconName='menu'|'close'|'briefcase'|'file'|'search'|'refresh'|'chevron'|'arrow'|'archive'|'filter';
const iconPaths:Record<IconName,ReactNode>={
  menu:<><path d="M4 7h16M4 12h16M4 17h16"/></>,
  close:<><path d="M5 5l14 14M19 5L5 19"/></>,
  briefcase:<><rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18"/></>,
  file:<><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
  search:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  refresh:<><path d="M20 7V3h-4M4 17v4h4M20 11a8 8 0 0 0-14-5l-2 2M4 13a8 8 0 0 0 14 5l2-2"/></>,
  chevron:<><path d="m9 18 6-6-6-6"/></>,
  arrow:<><path d="M5 12h14m-6-6 6 6-6 6"/></>,
  archive:<><rect x="4" y="4" width="16" height="4" rx="1"/><path d="M6 8v12h12V8M10 13h4"/></>,
  filter:<><path d="M4 5h16M7 12h10M10 19h4"/></>,
};
export function JWIcon({name,size=17}:{name:IconName;size?:number}) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24"
    fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round">
    {iconPaths[name]}
  </svg>;
}
export function CompanyAvatar({name}:{name:string|null}) {
  const initials=name?.trim().split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]?.toUpperCase()??'').join('')||'—';
  return <span className="c-company-avatar" aria-hidden="true">{initials}</span>;
}
export function FitValue({row}:{row:PersonalRow}) {
  const fit=row.assessment?.fitScore;
  if(fit===null||fit===undefined)return <span className="c-muted">—</span>;
  const freshness=row.assessment?.freshness;
  const color=freshness!=='CURRENT'?'c-fit-historical':fit>=80?'c-fit-high':fit>=60?'c-fit-mid':'c-fit-low';
  return <span className={color} title={freshness==='CURRENT'?'Valutazione sul fingerprint corrente':freshness==='STALE'?'Valutazione relativa a una versione precedente':'Validità non verificabile'}>
    {fit}{freshness==='CURRENT'?'':' · storico'}
  </span>;
}
export function WorkspaceShell({children}:{children:ReactNode}) {
  const [menuOpen,setMenuOpen]=useState(false);
  return <div className="c-workspace">
    <a className="c-skip" href="#c-main">Vai alle candidature</a>
    <button type="button" className="c-mobile-shield" tabIndex={menuOpen?0:-1}
      aria-label="Chiudi navigazione" onClick={()=>setMenuOpen(false)} hidden={!menuOpen}/>
    <aside className={'c-sidebar'+(menuOpen?' c-sidebar-open':'')} aria-label="Navigazione">
      <a href="/" className="c-brand"><span className="c-brand-mark">✳</span><b>Job Watch</b></a>
      <div className="c-workspace-id"><span className="c-user-mark">JW</span>
        <span><strong>Workspace personale</strong><small>Consultazione locale</small></span>
      </div>
      <nav className="c-nav" aria-label="Sezioni">
        <span className="c-nav-disabled" aria-disabled="true">Dashboard <small>Non disponibile</small></span>
        <a href="/" className="c-nav-item"><JWIcon name="briefcase"/> Opportunità</a>
        <span className="c-nav-disabled" aria-disabled="true">Aziende</span>
        <a href="/candidature" aria-current="page" className="c-nav-item c-nav-active">
          <JWIcon name="file"/> Candidature
        </a>
        <span className="c-nav-section">AUTOMAZIONE</span>
        <span className="c-nav-disabled" aria-disabled="true">Analisi AI</span>
        <span className="c-nav-disabled" aria-disabled="true">Pipeline e ATS</span>
        <span className="c-nav-disabled" aria-disabled="true"><JWIcon name="archive"/> Archivio</span>
      </nav>
      <p className="c-nav-footer">Modalità locale · Lettura dei dati sintetici, senza scritture.</p>
    </aside>
    <div className="c-main-column">
      <div className="c-topbar">
        <button type="button" className="c-mobile-menu" aria-label="Apri navigazione"
          aria-expanded={menuOpen} onClick={()=>setMenuOpen(true)}><JWIcon name="menu"/></button>
        <div className="c-breadcrumb"><span>Workspace</span><JWIcon name="chevron" size={12}/><b>Candidature</b></div>
        <span className="c-top-avatar" aria-hidden="true">JW</span>
      </div>
      <main id="c-main" className="c-main">{children}</main>
    </div>
  </div>;
}
