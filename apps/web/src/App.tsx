import { useEffect, useRef, useState } from 'react';
import { Icon, NavigationItem } from './components';
import Dashboard from './Dashboard';
import Opportunities from './Opportunities';

type Page = 'dashboard' | 'opportunities';
const currentPage = (): Page => window.location.hash === '#opportunities' || (!window.location.hash && window.location.search) ? 'opportunities' : 'dashboard';

export default function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const [mobileMenu, setMobileMenu] = useState(false);
  const [compact, setCompact] = useState(() => window.matchMedia('(max-width: 720px)').matches);
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const sync = () => { setPage(currentPage()); setMobileMenu(false); };
    const media = window.matchMedia('(max-width: 720px)');
    const resize = () => { setCompact(media.matches); setMobileMenu(false); };
    window.addEventListener('hashchange', sync);
    window.addEventListener('popstate', sync);
    media.addEventListener('change', resize);
    return () => { window.removeEventListener('hashchange', sync); window.removeEventListener('popstate', sync); media.removeEventListener('change', resize); };
  }, []);
  useEffect(() => { document.title = `Job Watch · ${page === 'dashboard' ? 'Dashboard' : 'Opportunità'}`; }, [page]);
  useEffect(() => {
    if (!mobileMenu || !compact) return;
    const previous = document.activeElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const controls = () => sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)');
    controls()?.[0]?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setMobileMenu(false); }
      if (event.key !== 'Tab') return;
      const nodes = controls(); if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', trap);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', trap); if (previous instanceof HTMLElement) previous.focus(); };
  }, [compact, mobileMenu]);
  const goToOpportunities = () => { window.location.hash = 'opportunities'; };
  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link" onClick={event => { event.preventDefault(); const main = document.getElementById("main-content"); main?.focus(); main?.scrollIntoView(); }}>Vai al contenuto principale</a>
      {mobileMenu && compact && <button type="button" className="nav-backdrop" aria-label="Chiudi menu" onClick={() => setMobileMenu(false)}/>}
      <aside id="workspace-navigation" ref={sidebar} inert={compact && !mobileMenu} className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`} aria-label="Navigazione principale">
        <div className="brand" translate="no"><div className="brand-symbol" aria-hidden="true"><span className="mark-corner"/><span className="mark-block"/></div><span>job<span className="brand-light">watch</span></span><button type="button" className="mobile-sidebar-close icon-button" aria-label="Chiudi navigazione" onClick={() => setMobileMenu(false)}><Icon name="close"/></button></div>
        <div className="workspace"><span className="workspace-avatar" aria-hidden="true">JW</span><div><strong>Il mio workspace</strong><small>Ambiente locale</small></div><Icon name="chevron" size={15}/></div>
        <nav className="nav-links" aria-label="Sezioni">
          <span className="nav-group-title">Il tuo spazio</span>
          <NavigationItem icon="grid" label="Dashboard" href="#dashboard" active={page === 'dashboard'}/>
          <NavigationItem icon="search" label="Opportunità" href="#opportunities" active={page === 'opportunities'}/>
          <NavigationItem icon="layers" label="Aziende" unavailable/>
          <NavigationItem icon="briefcase" label="Candidature" unavailable/>
          <span className="nav-group-title nav-group-gap">Operatività</span>
          <NavigationItem icon="check" label="Coda semantica" unavailable/>
          <NavigationItem icon="activity" label="Monitor" unavailable/>
          <div className="nav-bottom"><NavigationItem icon="settings" label="Impostazioni" unavailable/></div>
        </nav>
        <div className="sidebar-footer"><span className="side-footer-indicator"/>Consultazione locale <span>v0.2</span></div>
      </aside>
      <div className="main-area" inert={compact && mobileMenu}>
        <header className="app-topbar"><div className="header-left"><button ref={menuButton} type="button" className="mobile-menu-button" onClick={() => setMobileMenu(true)} aria-label="Apri navigazione" aria-expanded={mobileMenu} aria-controls="workspace-navigation"><Icon name="menu" size={21}/></button><span className="breadcrumb-root">Workspace</span><span className="breadcrumb-divider">/</span><strong>{page === 'dashboard' ? 'Dashboard' : 'Opportunità'}</strong></div><div className="header-right"><span className="demo-indicator"><span/>Sola lettura</span><span className="profile-icon" aria-label="Workspace personale">JW</span></div></header>
        <main id="main-content" className="main-content" tabIndex={-1}>
          {page === 'dashboard' ? <Dashboard onExplore={goToOpportunities}/> : <Opportunities/>}
        </main>
      </div>
    </div>
  );
}
