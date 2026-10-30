import type { ReactNode } from 'react';
type IconName = 'grid' | 'search' | 'layers' | 'briefcase' | 'check' | 'activity' | 'settings' | 'arrow' | 'refresh' | 'menu' | 'close' | 'filter' | 'external' | 'info' | 'circle' | 'chevron';
export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
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

export function NavigationItem({ icon, label, active, onClick, unavailable = false, href = '#' }: {
  icon: IconName; label: string; active?: boolean; onClick?: () => void; unavailable?: boolean; href?: string;
}) {
  const children = <><Icon name={icon}/><span>{label}</span>{unavailable && <span className="soon">Presto</span>}</>;
  if (unavailable) return <span className="nav-item nav-item-disabled" aria-disabled="true">{children}</span>;
  return <a className={`nav-item${active ? ' is-active' : ''}`} href={href} onClick={onClick} aria-current={active ? 'page' : undefined}>{children}</a>;
}

export function SectionHeading({ title, description, trailing }: { title: string; description?: string; trailing?: ReactNode }) {
  return <div className="section-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div>{trailing}</div>;
}
